from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, g
from functools import wraps
import sqlite3
import hashlib
import os
import markdown
import bleach
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['DATABASE'] = os.environ.get('DATABASE', 'library.db')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'static/uploads')

# Разрешенные расширения для обложек
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Создаем папку для загрузок, если её нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.context_processor
def utility_processor():
    """Делает функции доступными во всех шаблонах"""
    def get_user_role():
        """Возвращает роль текущего пользователя (admin/moderator/user)"""
        if 'user_id' not in session:
            return None
        user = query_db('SELECT role_id FROM users WHERE id = ?', [session['user_id']], one=True)
        if user:
            role = query_db('SELECT name FROM roles WHERE id = ?', [user['role_id']], one=True)
            return role['name']
        return None
    
    def get_user_full_name():
        """Возвращает ФИО текущего пользователя для отображения в шапке"""
        if 'user_id' not in session:
            return None
        user = query_db('SELECT last_name, first_name, middle_name FROM users WHERE id = ?', 
                        [session['user_id']], one=True)
        if user:
            parts = [user['last_name'], user['first_name']]
            if user['middle_name']:
                parts.append(user['middle_name'])
            return ' '.join(parts)
        return None
    
    return dict(get_user_role=get_user_role, get_user_full_name=get_user_full_name)

# --- Функции для работы с БД ---
def get_db():
    """Получение соединения с БД"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row  # Чтобы возвращать словари
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Закрытие соединения с БД"""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    """Выполнение запроса SELECT и возврат результата в виде словарей."""
    db = get_db()
    cur = db.cursor() # Явно создаем курсор
    cur.execute(query, args)
    rv = cur.fetchall()
    
    # Преобразуем результат в список словарей
    desc = cur.description
    column_names = [col[0] for col in desc]
    data_as_dicts = [dict(zip(column_names, row)) for row in rv]
    # ----------------------------------------------------------------
    
    cur.close()
    return (data_as_dicts[0] if data_as_dicts else None) if one else data_as_dicts

def execute_db(query, args=(), commit=True):
    """Выполнение запроса INSERT/UPDATE/DELETE"""
    db = get_db()
    cur = db.execute(query, args)
    if commit:
        db.commit()
    cur.close()
    return cur.lastrowid

# Декораторы для проверки прав доступа
def login_required(f):
    """Декоратор - требует аутентификации"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Для выполнения данного действия необходимо пройти процедуру аутентификации', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Декоратор - требует роль администратора"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        user = query_db('SELECT role_id FROM users WHERE id = ?', [session['user_id']], one=True)
        role = query_db('SELECT name FROM roles WHERE id = ?', [user['role_id']], one=True)
        if role['name'] != 'admin':
            flash('У вас недостаточно прав для выполнения данного действия', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def moderator_or_admin_required(f):
    """Декоратор - требует роль модератора или администратора"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        user = query_db('SELECT role_id FROM users WHERE id = ?', [session['user_id']], one=True)
        role = query_db('SELECT name FROM roles WHERE id = ?', [user['role_id']], one=True)
        if role['name'] not in ['admin', 'moderator']:
            flash('У вас недостаточно прав для выполнения данного действия', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Вспомогательные функции 
def allowed_file(filename):
    """Проверка расширения файла"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_role():
    """Получение роли текущего пользователя"""
    if 'user_id' not in session:
        return None
    user = query_db('SELECT role_id FROM users WHERE id = ?', [session['user_id']], one=True)
    if user:
        role = query_db('SELECT name FROM roles WHERE id = ?', [user['role_id']], one=True)
        return role['name']
    return None

def get_user_full_name():
    """Получение ФИО текущего пользователя"""
    if 'user_id' not in session:
        return None
    user = query_db('SELECT last_name, first_name, middle_name FROM users WHERE id = ?', 
                    [session['user_id']], one=True)
    if user:
        parts = [user['last_name'], user['first_name']]
        if user['middle_name']:
            parts.append(user['middle_name'])
        return ' '.join(parts)
    return None

# Маршруты 
@app.route('/')
def index():
    """Главная страница со списком книг и поиском"""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    # Получаем параметры поиска из URL
    search_title = request.args.get('title', '')
    search_author = request.args.get('author', '')
    search_genres = request.args.getlist('genres')
    search_years = request.args.getlist('years')
    search_pages_from = request.args.get('pages_from', type=int)
    search_pages_to = request.args.get('pages_to', type=int)
    
    # SQL запрос с фильтрацией
    query = """
        SELECT DISTINCT b.*, 
               c.filename as cover_filename,
               AVG(r.rating) as avg_rating,
               COUNT(DISTINCT r.id) as reviews_count
        FROM books b
        LEFT JOIN covers c ON b.id = c.book_id
        LEFT JOIN reviews r ON b.id = r.book_id
        LEFT JOIN book_genres bg ON b.id = bg.book_id
        LEFT JOIN genres g ON bg.genre_id = g.id
        WHERE 1=1
    """
    count_query = "SELECT COUNT(DISTINCT b.id) as count FROM books b LEFT JOIN book_genres bg ON b.id = bg.book_id LEFT JOIN genres g ON bg.genre_id = g.id WHERE 1=1"
    params = []
    
    # Фильтр по названию (частичное совпадение)
    if search_title:
        query += " AND b.title LIKE ?"
        count_query += " AND b.title LIKE ?"
        params.append(f'%{search_title}%')
    
    # Фильтр по автору (частичное совпадение)
    if search_author:
        query += " AND b.author LIKE ?"
        count_query += " AND b.author LIKE ?"
        params.append(f'%{search_author}%')
    
    # Фильтр по жанрам (мультиселект)
    if search_genres:
        placeholders = ','.join('?' * len(search_genres))
        query += f" AND g.id IN ({placeholders})"
        count_query += f" AND g.id IN ({placeholders})"
        params.extend(search_genres)
    
    # Фильтр по годам (мультиселект)
    if search_years:
        placeholders = ','.join('?' * len(search_years))
        query += f" AND b.year IN ({placeholders})"
        count_query += f" AND b.year IN ({placeholders})"
        params.extend(search_years)
    
    # Фильтрация по объему
    if search_pages_from:
        query += " AND b.pages >= ?"
        count_query += " AND b.pages >= ?"
        params.append(search_pages_from)
    if search_pages_to:
        query += " AND b.pages <= ?"
        count_query += " AND b.pages <= ?"
        params.append(search_pages_to)
    
    # Группировка и сортировка
    query += " GROUP BY b.id ORDER BY b.year DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    
    books = query_db(query, params)
    
    # Получение общего количества (для пагинации)
    total = query_db(count_query, params[:-2] if params else [])  
    total_count = total[0]['count'] if total else 0
    
    # Получение жанров для каждой книги
    for book in books:
        genres = query_db("""
            SELECT g.* FROM genres g
            JOIN book_genres bg ON g.id = bg.genre_id
            WHERE bg.book_id = ?
        """, [book['id']])
        book['genres'] = genres
    
    # Для формы поиска: список годов из БД и список жанров
    years = query_db("SELECT DISTINCT year FROM books ORDER BY year DESC")
    genres_list = query_db("SELECT * FROM genres ORDER BY name")
    
    # Расчет страниц для пагинации
    total_pages = (total_count + per_page - 1) // per_page  # округление вверх
    if total_pages > 1:
        pages = range(1, total_pages + 1)
    else:
        pages = []
    
    return render_template('index.html', 
                         books=books, 
                         page=page, 
                         pages=pages,
                         years=years,
                         genres_list=genres_list,
                         search_params={
                             'title': search_title,
                             'author': search_author,
                             'genres': search_genres,
                             'years': search_years,
                             'pages_from': search_pages_from,
                             'pages_to': search_pages_to
                         })

@app.route('/book/<int:book_id>')
def book_detail(book_id):
    """Страница просмотра книги"""
    book = query_db("""
        SELECT b.*, c.filename as cover_filename
        FROM books b
        LEFT JOIN covers c ON b.id = c.book_id
        WHERE b.id = ?
    """, [book_id], one=True)
    
    if not book:
        abort(404)
    
    # Жанры
    genres = query_db("""
        SELECT g.* FROM genres g
        JOIN book_genres bg ON g.id = bg.genre_id
        WHERE bg.book_id = ?
    """, [book_id])
    
    # Преобразование описания из Markdown в HTML с санитайзингом
    allowed_tags = ['p', 'br', 'strong', 'em', 'blockquote', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4']
    book['description_html'] = bleach.clean(
        markdown.markdown(book['description']),
        tags=allowed_tags
    )
    
    # Рецензии 
    reviews = query_db("""
        SELECT r.*, u.last_name, u.first_name, u.middle_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.book_id = ?
        ORDER BY r.created_at DESC
    """, [book_id])
    
    # Преобразование Markdown в HTML для рецензий
    for review in reviews:
        review['text_html'] = markdown.markdown(review['text'])
    
    # Проверка, писал ли пользователь рецензию
    user_review = None
    if session.get('user_id'):
        user_review = query_db("""
            SELECT * FROM reviews WHERE book_id = ? AND user_id = ?
        """, [book_id, session['user_id']], one=True)

        if user_review:
            user_review['text_html'] = markdown.markdown(user_review['text'])
    
    return render_template('book_detail.html', 
                         book=book, 
                         genres=genres, 
                         reviews=reviews,
                         user_review=user_review)

@app.route('/book/add', methods=['GET', 'POST'])
@moderator_or_admin_required
def add_book():
    """Добавление новой книги"""
    genres_list = query_db("SELECT * FROM genres ORDER BY name")
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        year = request.form.get('year', type=int)
        publisher = request.form.get('publisher', '').strip()
        author = request.form.get('author', '').strip()
        pages = request.form.get('pages', type=int)
        genre_ids = request.form.getlist('genres')
        
        # Валидация
        error = False
        if not title:
            flash('Название обязательно', 'danger')
            error = True
        if not description:
            flash('Описание обязательно', 'danger')
            error = True
        if not year or year < 0 or year > 2026:
            flash('Некорректный год', 'danger')
            error = True
        if not publisher:
            flash('Издательство обязательно', 'danger')
            error = True
        if not author:
            flash('Автор обязателен', 'danger')
            error = True
        if not pages or pages <= 0:
            flash('Объем должен быть положительным числом', 'danger')
            error = True
        if not genre_ids:
            flash('Выберите хотя бы один жанр', 'danger')
            error = True
        
        # Проверка файла обложки
        cover_file = request.files.get('cover')
        if not cover_file or cover_file.filename == '':
            flash('Обложка обязательна', 'danger')
            error = True
        
        if error:
            return render_template('book_form.html', 
                                 book=None, 
                                 genres=genres_list,
                                 form_data=request.form)
        
        # Санитайзинг описания
        description = bleach.clean(description)
        
        # Сохранение в БД
        db = get_db()
        try:
            # 1. Добавление книги
            book_id = execute_db("""
                INSERT INTO books (title, description, year, publisher, author, pages)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [title, description, year, publisher, author, pages], commit=False)
            
            # 2. Добавление жанров
            for genre_id in genre_ids:
                execute_db("""
                    INSERT INTO book_genres (book_id, genre_id)
                    VALUES (?, ?)
                """, [book_id, genre_id], commit=False)
            
            # 3. Обработка обложки
            if cover_file and allowed_file(cover_file.filename):
                file_data = cover_file.read()
                md5_hash = hashlib.md5(file_data).hexdigest()
                
                # Проверка, существует ли уже такой файл по MD5
                existing_cover = query_db("""
                    SELECT id, filename FROM covers WHERE md5_hash = ?
                """, [md5_hash], one=True)
                
                if existing_cover:
                    # Обложка уже есть - используем существующую
                    filename = existing_cover['filename']
                    cover_id = existing_cover['id']
                    
                    # Связываем существующую обложку с новой книгой
                    execute_db("""
                        UPDATE covers SET book_id = ? WHERE id = ?
                    """, [book_id, cover_id], commit=False)
                else:
                    # Новая обложка: сначала вставляем запись с временным filename
                    extension = cover_file.filename.rsplit('.', 1)[1].lower()
                    temp_filename = 'temp'
                    
                    cover_id = execute_db("""
                        INSERT INTO covers (filename, mime_type, md5_hash, book_id)
                        VALUES (?, ?, ?, ?)
                    """, [temp_filename, cover_file.mimetype, md5_hash, book_id], commit=False)
                    
                    # Теперь у нас есть cover_id и используем его как имя файла
                    filename = f"{cover_id}.{extension}"
                    
                    # Обновляем filename в БД
                    execute_db("""
                        UPDATE covers SET filename = ? WHERE id = ?
                    """, [filename, cover_id], commit=False)
                    
                    # Сохраняем файл в файловую систему
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    with open(filepath, 'wb') as f:
                        f.write(file_data)
                
                db.commit()
                flash('Книга успешно добавлена', 'success')
                return redirect(url_for('book_detail', book_id=book_id))
            else:
                db.rollback()
                flash('Недопустимый формат файла обложки', 'danger')
                
        except Exception as e:
            db.rollback()
            flash(f'При сохранении данных возникла ошибка: {str(e)}', 'danger')
    
    return render_template('book_form.html', book=None, genres=genres_list)

@app.route('/book/<int:book_id>/edit', methods=['GET', 'POST'])
@moderator_or_admin_required
def edit_book(book_id):
    """Редактирование книги"""
    book = query_db("SELECT * FROM books WHERE id = ?", [book_id], one=True)
    if not book:
        abort(404)
    
    genres_list = query_db("SELECT * FROM genres ORDER BY name")
    book_genres = query_db("SELECT genre_id FROM book_genres WHERE book_id = ?", [book_id])
    book_genre_ids = [g['genre_id'] for g in book_genres]
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        year = request.form.get('year', type=int)
        publisher = request.form.get('publisher', '').strip()
        author = request.form.get('author', '').strip()
        pages = request.form.get('pages', type=int)
        genre_ids = request.form.getlist('genres')
        
        # Валидация
        error = False
        if not title:
            flash('Название обязательно', 'danger')
            error = True
        if not description:
            flash('Описание обязательно', 'danger')
            error = True
        if not year or year < 0 or year > 2026:
            flash('Некорректный год', 'danger')
            error = True
        if not publisher:
            flash('Издательство обязательно', 'danger')
            error = True
        if not author:
            flash('Автор обязателен', 'danger')
            error = True
        if not pages or pages <= 0:
            flash('Объем должен быть положительным числом', 'danger')
            error = True
        if not genre_ids:
            flash('Выберите хотя бы один жанр', 'danger')
            error = True
        
        if error:
            return render_template('book_form.html', 
                                 book=book, 
                                 genres=genres_list,
                                 book_genre_ids=book_genre_ids,
                                 form_data=request.form)
        
        # Санитайзинг описания
        description = bleach.clean(description)
        
        db = get_db()
        try:
            # Обновление книги
            execute_db("""
                UPDATE books 
                SET title = ?, description = ?, year = ?, publisher = ?, author = ?, pages = ?
                WHERE id = ?
            """, [title, description, year, publisher, author, pages, book_id])
            
            # Обновление жанров
            execute_db("DELETE FROM book_genres WHERE book_id = ?", [book_id])
            for genre_id in genre_ids:
                execute_db("""
                    INSERT INTO book_genres (book_id, genre_id)
                    VALUES (?, ?)
                """, [book_id, genre_id])
            
            db.commit()
            flash('Книга успешно обновлена', 'success')
            return redirect(url_for('book_detail', book_id=book_id))
        except Exception as e:
            db.rollback()
            flash(f'При сохранении данных возникла ошибка: {str(e)}', 'danger')
    
    return render_template('book_form.html', 
                         book=book, 
                         genres=genres_list,
                         book_genre_ids=book_genre_ids)

@app.route('/book/<int:book_id>/delete', methods=['POST'])
@admin_required
def delete_book(book_id):
    """Удаление книги"""
    book = query_db("SELECT * FROM books WHERE id = ?", [book_id], one=True)
    if not book:
        abort(404)
    
    # Получаем информацию об обложке
    cover = query_db("SELECT filename FROM covers WHERE book_id = ?", [book_id], one=True)
    
    db = get_db()
    try:
        # Удаляем файл обложки
        if cover:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], cover['filename'])
            if os.path.exists(filepath):
                os.remove(filepath)
        
        # Удаляем книгу (каскадно удалятся связанные записи)
        execute_db("DELETE FROM books WHERE id = ?", [book_id])
        db.commit()
        flash(f'Книга "{book["title"]}" успешно удалена', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'danger')
    
    return redirect(url_for('index'))

@app.route('/book/<int:book_id>/review', methods=['GET', 'POST'])
@login_required
def add_review(book_id): 
    
    book = query_db("SELECT * FROM books WHERE id = ?", [book_id], one=True)
    if not book:
        abort(404)
    
    # Проверка, не писал ли пользователь уже рецензию
    existing = query_db("""
        SELECT * FROM reviews WHERE book_id = ? AND user_id = ?
    """, [book_id, session['user_id']], one=True)
    
    if existing:
        flash('Вы уже оставили рецензию на эту книгу', 'warning')
        return redirect(url_for('book_detail', book_id=book_id))
    
    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        text = request.form.get('text', '').strip()
        
        error = False
        if rating is None or rating < 0 or rating > 5:
            flash('Некорректная оценка', 'danger')
            error = True
        if not text:
            flash('Текст рецензии обязателен', 'danger')
            error = True
        
        if error:
            return render_template('review_form.html', book=book, form_data=request.form)
        
        # Санитайзинг текста
        text = bleach.clean(text)
        
        try:
            execute_db("""
                INSERT INTO reviews (book_id, user_id, rating, text)
                VALUES (?, ?, ?, ?)
            """, [book_id, session['user_id'], rating, text])
             
            flash('Рецензия успешно добавлена!', 'success')
            return redirect(url_for('book_detail', book_id=book_id))
        except Exception as e:
            flash(f'Ошибка при сохранении: {str(e)}', 'danger')
    
    return render_template('review_form.html', book=book)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        login_input = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        
        user = query_db("""
            SELECT u.*, r.name as role_name 
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.login = ?
        """, [login_input], one=True)
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_login'] = user['login']
            session['user_role'] = user['role_name']
            
            if remember:
                session.permanent = True
            
            flash('Вы успешно вошли в систему', 'success')
            return redirect(request.args.get('next', url_for('index')))
        else:
            flash('Невозможно аутентифицироваться с указанными логином и паролем', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Выход из системы"""
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)