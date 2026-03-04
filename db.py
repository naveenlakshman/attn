import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash
from config import DB_PATH

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # ---------- USERS (Admin/Staff) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','staff')),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # ---------- COURSES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL UNIQUE,
            duration TEXT,
            fee REAL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ---------- BATCHES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_name TEXT NOT NULL,
            course_id INTEGER NOT NULL,
            start_date TEXT,
            end_date TEXT,
            timing TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(batch_name, course_id),
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE RESTRICT
        )
    """)

    # ---------- STUDENTS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            mobile_number TEXT,
            registration_number TEXT NOT NULL UNIQUE,
            course_id INTEGER,
            address TEXT,
            qualification TEXT,
            date_of_joining TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE SET NULL
        )
    """)

    # ---------- STUDENT <-> BATCHES (Multiple batches per student) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            assigned_on TEXT NOT NULL,
            UNIQUE(student_id, batch_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE CASCADE
        )
    """)

    # ---------- ATTENDANCE ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            att_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('P','A')),
            marked_by INTEGER,
            marked_at TEXT NOT NULL,
            UNIQUE(student_id, att_date),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(marked_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    conn.commit()

    # Create default admin if not exists
    create_default_admin(conn)

    conn.close()

def create_default_admin(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    exists = cur.fetchone()
    if exists:
        return

    now = datetime.now().isoformat(timespec="seconds")
    password_hash = generate_password_hash("Admin@123")

    cur.execute("""
        INSERT INTO users (full_name, username, password_hash, role, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("Administrator", "admin", password_hash, "admin", 1, now))

    conn.commit()