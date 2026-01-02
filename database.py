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

def get_year_range():
    """Get the range of years from student IDs in the database."""
    try:
        with get_db_connection(STUDENTS_DB) as conn:
            # Extract year from student ID (first 4 characters)
            result = conn.execute("""
                SELECT 
                    MIN(CAST(substr(ID, 1, 4) AS INTEGER)) as min_year,
                    MAX(CAST(substr(ID, 1, 4) AS INTEGER)) as max_year
                FROM students
                WHERE substr(ID, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
            """).fetchone()
            
            if result and result['min_year'] and result['max_year']:
                # Start from 2021 or the minimum year found, whichever is earlier
                min_year = min(2021, result['min_year'])
                return {"min_year": min_year, "max_year": result['max_year']}
            else:
                # Default range if no data
                return {"min_year": 2021, "max_year": datetime.datetime.now().year}
    except Exception as e:
        print(f"Error getting year range: {e}")
        # Default range on error
        return {"min_year": 2021, "max_year": datetime.datetime.now().year}


def get_mess_stats(month=None, year=None):
    """
    Returns stats: {
        "daily_counts": { "YYYY-MM-DD": { "BREAKFAST": 10, "LUNCH": 20 } },
        "monthly_total": 500,
        "session_totals": { "BREAKFAST": 120, ... }
    }
    """
    if not month or not year:
        now = datetime.datetime.now()
        month, year = now.month, now.year
    
    # Construct filename manually since get_monthly_db_path uses current time default
    # but we want specific month
    filename = f"mess-{year}-{int(month):02d}.db"
    db_path = os.path.join(DB_DIR, filename)
    
    if not os.path.exists(db_path):
        return {"daily_counts": {}, "monthly_total": 0, "session_totals": {}}

    stats = {
        "daily_counts": {},
        "monthly_total": 0,
        "session_totals": {}
    }
    
    try:
        with get_db_connection(db_path) as conn:
            # Group by Date and Session
            rows = conn.execute("""
                SELECT 
                    date(TIMESTAMP) as entry_date, 
                    SESSION_NAME, 
                    COUNT(*) as count 
                FROM mess_entries 
                GROUP BY date(TIMESTAMP), SESSION_NAME
            """).fetchall()
            
            for row in rows:
                date_str = row['entry_date']
                session = row['SESSION_NAME']
                count = row['count']
                
                # Monthly Total
                stats["monthly_total"] += count
                
                # Session Totals
                stats["session_totals"][session] = stats["session_totals"].get(session, 0) + count
                
                # Daily Counts
                if date_str not in stats["daily_counts"]:
                    stats["daily_counts"][date_str] = {}
                stats["daily_counts"][date_str][session] = count
                
    except Exception as e:
        print(f"Stats Error: {e}")
        
    return stats

def get_mess_entries_csv_data(month_year=None):
    # Retrieve all entries from the monthly DB
    # month_year format: 'YYYY-MM'
    db_path = get_monthly_db_path("mess") 
    
    if month_year:
         try:
             y, m = month_year.split('-')
             filename = f"mess-{y}-{int(m):02d}.db"
             db_path = os.path.join(DB_DIR, filename)
         except: pass

    if not os.path.exists(db_path):
        return []

    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM mess_entries ORDER BY TIMESTAMP DESC").fetchall()
        
        results = []
        for row in rows:
             # Get student name
            student = get_student(row['STUDENT_ID'])
            name = student['NAME'] if student else "Unknown"
            if row['STUDENT_ID'] == "IIITKOTAUSER": name = "Guest"
            
            results.append({
                "Timestamp": row['TIMESTAMP'],
                "Student ID": row['STUDENT_ID'],
                "Name": name,
                "Session": row['SESSION_NAME']
            })
        return results

def init_mess_db():
    """Initialize the mess_entries table in the monthly mess database."""
    db_path = get_monthly_db_path("mess")
    with get_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mess_entries (
                ID TEXT PRIMARY KEY,
                STUDENT_ID TEXT,
                SESSION_NAME TEXT,
                TIMESTAMP DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def log_mess_entry(student_id, session_name):
    db_path = get_monthly_db_path("mess")
    init_mess_db() # Ensure table exists
    
    uid = str(uuid.uuid4())
    try:
        with get_db_connection(db_path) as conn:
            conn.execute("INSERT INTO mess_entries (ID, STUDENT_ID, SESSION_NAME) VALUES (?, ?, ?)", 
                         (uid, student_id, session_name))
            conn.commit()
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False


def has_eaten(student_id, session_name):
    db_path = get_monthly_db_path("mess")
    if not os.path.exists(db_path):
        return False
        
    # Check if user has an entry for this session TODAY
    today_str = datetime.date.today().isoformat()
    
    with get_db_connection(db_path) as conn:
        row = conn.execute("""
            SELECT 1 FROM mess_entries 
            WHERE STUDENT_ID = ? 
            AND SESSION_NAME = ?
            AND date(TIMESTAMP) = ?
        """, (student_id, session_name, today_str)).fetchone()
        return row is not None

def get_recent_mess_entries(session_name, limit=30):
    """Get recent mess entries for a specific session today."""
    db_path = get_monthly_db_path("mess")
    if not os.path.exists(db_path):
        return []
    
    today_str = datetime.date.today().isoformat()
    
    with get_db_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT STUDENT_ID, SESSION_NAME, TIMESTAMP 
            FROM mess_entries 
            WHERE SESSION_NAME = ? AND date(TIMESTAMP) = ?
            ORDER BY TIMESTAMP DESC
            LIMIT ?
        """, (session_name, today_str, limit)).fetchall()
        
        results = []
        for row in rows:
            student = get_student(row['STUDENT_ID'])
            name = student['NAME'] if student else "Unknown"
            if row['STUDENT_ID'] == "IIITKOTAUSER":
                name = "Guest User"
            
            results.append({
                "student_id": row['STUDENT_ID'],
                "name": name,
                "session": row['SESSION_NAME'],
                "timestamp": row['TIMESTAMP']
            })
        return results

def get_mess_entries_csv_data(month_year=None):
    # Retrieve all entries from the monthly DB
    # month_year format: 'YYYY-MM'
    if not month_year:
        now = datetime.datetime.now()
        prefix = "mess" # Uses get_monthly_db_path logic internally but we need to construct filename manually for specific months if needed
        # For now, let's use the current month logic in get_monthly_db_path or verify how to support historic
        db_path = get_monthly_db_path("mess")
    else:
        # Construct path manually for historic export if needed, 
        # but for MVP let's stick to current month or simplistic approach
        db_path = get_monthly_db_path("mess") 

    if not os.path.exists(db_path):
        return []

    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM mess_entries ORDER BY TIMESTAMP DESC").fetchall()
        
        results = []
        for row in rows:
             # Get student name
            student = get_student(row['STUDENT_ID'])
            name = student['NAME'] if student else "Unknown"
            if row['STUDENT_ID'] == "IIITKOTAUSER": name = "Guest"
            
            results.append({
                "Timestamp": row['TIMESTAMP'],
                "Student ID": row['STUDENT_ID'],
                "Name": name,
                "Session": row['SESSION_NAME']
            })
        return results