import sqlite3
import datetime
import uuid
import os
from config import DB_DIR, STUDENTS_DB

def get_db_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_students_db():
    with get_db_connection(STUDENTS_DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS students (ID TEXT PRIMARY KEY, NAME TEXT)")
        conn.commit()

def get_monthly_db_path(prefix):
    now = datetime.datetime.now()
    filename = f"{prefix}-{now.year}-{now.month:02d}.db"
    return os.path.join(DB_DIR, filename)

def init_monthly_db(path, table_name):
    with get_db_connection(path) as conn:
        if table_name == 'entries':
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    CUIDV2 TEXT PRIMARY KEY,
                    STUDENT_ID TEXT,
                    TIMESTAMP DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        elif table_name == 'logs':
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    CUIDV2 TEXT PRIMARY KEY,
                    LOG TEXT,
                    STUDENT_ID TEXT,
                    TIMESTAMP DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()

def get_student(student_id):
    try:
        with get_db_connection(STUDENTS_DB) as conn:
            cur = conn.execute("SELECT * FROM students WHERE ID = ?", (student_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None

def log_entry(direction, student_id):
    db_path = get_monthly_db_path(direction)
    init_monthly_db(db_path, 'entries')
    
    cuid = str(uuid.uuid4())
    try:
        with get_db_connection(db_path) as conn:
            conn.execute("INSERT INTO entries (CUIDV2, STUDENT_ID) VALUES (?, ?)", 
                         (cuid, student_id))
            conn.commit()
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False

def log_system_message(message, student_id="System", level="info"):
    db_path = get_monthly_db_path("logs")
    init_monthly_db(db_path, 'logs')
    
    # We append level to message for simplicity in this schema
    full_msg = f"[{level.upper()}] {message}"
    cuid = str(uuid.uuid4())
    
    with get_db_connection(db_path) as conn:
        conn.execute("INSERT INTO logs (CUIDV2, LOG, STUDENT_ID) VALUES (?, ?, ?)", 
                     (cuid, full_msg, student_id))
        conn.commit()

def get_recent_entries(direction, limit=30):
    db_path = get_monthly_db_path(direction)
    if not os.path.exists(db_path):
        return []
    
    entries = []
    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY TIMESTAMP DESC LIMIT ?", (limit,)).fetchall()
        for row in rows:
            student = get_student(row['STUDENT_ID'])
            
            # Handle Guest User
            img_path = f"/api/images/{row['STUDENT_ID']}.png"
            name = student['NAME'] if student else "Unknown"
            
            if row['STUDENT_ID'] == "IIITKOTAUSER":
                img_path = "/api/images/guest.png"
                name = "Guest User"
                
            entries.append({
                "student_id": row['STUDENT_ID'],
                "timestamp": row['TIMESTAMP'],
                "name": name,
                "image_path": img_path
            })
    return entries

# Initialize on load
init_students_db()