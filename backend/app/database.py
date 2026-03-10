import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = Path('data/app.db')


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        doc_id TEXT UNIQUE NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_type TEXT NOT NULL,
        chunks_indexed INTEGER NOT NULL,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
    
    conn.commit()
    conn.close()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_user(username: str, password_hash: str) -> int:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
                  (username, password_hash, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return c.lastrowid


def get_user_by_username(username: str):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE username = ?', (username,))
        return c.fetchone()


def create_file_record(user_id: int, doc_id: str, filename: str, file_path: str, file_type: str, chunks: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO files (user_id, doc_id, filename, file_path, file_type, chunks_indexed, uploaded_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, doc_id, filename, file_path, file_type, chunks, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return c.lastrowid


def get_user_files(user_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM files WHERE user_id = ? ORDER BY uploaded_at DESC', (user_id,))
        return [dict(row) for row in c.fetchall()]


def delete_file_record(file_id: int, user_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM files WHERE id = ? AND user_id = ?', (file_id, user_id))
        file = c.fetchone()
        if file:
            c.execute('DELETE FROM files WHERE id = ?', (file_id,))
            conn.commit()
            return dict(file)
    return None
