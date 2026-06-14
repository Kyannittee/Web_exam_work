import sqlite3
import hashlib
import os
from werkzeug.security import generate_password_hash

DATABASE = 'library.db'

def init_db():
    """Создание всех таблиц"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Таблица ролей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
    ''')
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            middle_name TEXT,
            role_id INTEGER NOT NULL,
            FOREIGN KEY (role_id) REFERENCES roles (id)
        )
    ''')
    
    # Таблица жанров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    # Таблица книг
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            year INTEGER NOT NULL,
            publisher TEXT NOT NULL,
            author TEXT NOT NULL,
            pages INTEGER NOT NULL
        )
    ''')
    
    # Связь книг и жанров (многие ко многим)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS book_genres (
            book_id INTEGER NOT NULL,
            genre_id INTEGER NOT NULL,
            PRIMARY KEY (book_id, genre_id),
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
            FOREIGN KEY (genre_id) REFERENCES genres (id)
        )
    ''')
    
    # Таблица обложек
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS covers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            md5_hash TEXT NOT NULL UNIQUE,
            book_id INTEGER NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
        )
    ''')
    
    # Таблица рецензий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Таблицы созданы")

def insert_test_data():
    """Заполнение тестовыми данными"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Добавление ролей
    roles = [
        ('admin', 'Полный доступ'),
        ('moderator', 'Может редактировать книги и модерировать рецензии'),
        ('user', 'Может оставлять рецензии')
    ]
    cursor.executemany('INSERT OR IGNORE INTO roles (name, description) VALUES (?, ?)', roles)
    
    # Добавление пользователей
    users = [
        ('admin', generate_password_hash('admin123'), 'Букарева', 'Анна', 'Викторовна', 1),
        ('moderator', generate_password_hash('mod123'), 'Петров', 'Петр', 'Петрович', 2),
        ('user1', generate_password_hash('user123'), 'Алексеев', 'Алексей', 'Алексеевич', 3),
        ('user2', generate_password_hash('qwerty123'), 'Аннушкина', 'Анна', 'Анатольевна', 3)
    ]
    cursor.executemany('INSERT OR IGNORE INTO users (login, password_hash, last_name, first_name, middle_name, role_id) VALUES (?, ?, ?, ?, ?, ?)', users)
    
    # Добавление жанров
    genres = [
        'Роман', 'Детектив', 'Фантастика', 'Научная литература', 'Поэзия', 
        'История', 'Биография', 'Приключения', 'Ужасы', 'Комедия'
    ]
    for genre in genres:
        cursor.execute('INSERT OR IGNORE INTO genres (name) VALUES (?)', (genre,))
    
    # Получение ID жанров
    cursor.execute('SELECT id, name FROM genres')
    
    conn.commit()
    conn.close()
    print("Тестовые данные добавлены")

if __name__ == '__main__':
    if os.path.exists(DATABASE):
        print(f"База данных {DATABASE} уже существует.")
        answer = input("Пересоздать БД? Все данные будут потеряны! (y/N): ")
        if answer.lower() != 'y':
            print("Операция отменена.")
            exit()
        os.remove(DATABASE)
        print("Старая БД удалена")
    
    init_db()
    insert_test_data()
    print("База данных готова к использованию!")