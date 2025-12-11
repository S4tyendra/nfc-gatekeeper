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

# === AUDIT LOG FUNCTIONS ===

def get_all_entries(direction='all', month=None, student_id=None, limit=100):
    """Get entries from database with filters for audit log."""
    entries = []
    
    # Determine which database files to query
    if month:
        year, mon = month.split('-')
        if direction == 'all':
            db_files = [
                (os.path.join(DB_DIR, f"in-{year}-{mon}.db"), 'in'),
                (os.path.join(DB_DIR, f"out-{year}-{mon}.db"), 'out')
            ]
        else:
            db_files = [(os.path.join(DB_DIR, f"{direction}-{year}-{mon}.db"), direction)]
    else:
        # Use current month
        now = datetime.datetime.now()
        if direction == 'all':
            db_files = [
                (get_monthly_db_path('in'), 'in'),
                (get_monthly_db_path('out'), 'out')
            ]
        else:
            db_files = [(get_monthly_db_path(direction), direction)]
    
    for db_path, dir_type in db_files:
        if not os.path.exists(db_path):
            continue
            
        try:
            with get_db_connection(db_path) as conn:
                query = "SELECT * FROM entries"
                params = []
                
                if student_id:
                    query += " WHERE STUDENT_ID LIKE ?"
                    params.append(f"%{student_id}%")
                
                query += " ORDER BY TIMESTAMP DESC"
                
                if limit:
                    query += f" LIMIT {int(limit)}"
                
                rows = conn.execute(query, params).fetchall()
                
                for row in rows:
                    student = get_student(row['STUDENT_ID'])
                    
                    # Handle Guest User
                    name = student['NAME'] if student else "Unknown"
                    if row['STUDENT_ID'] == "IIITKOTAUSER":
                        name = "Guest User"
                    
                    entries.append({
                        "cuidv2": row['CUIDV2'],
                        "student_id": row['STUDENT_ID'],
                        "timestamp": row['TIMESTAMP'],
                        "direction": dir_type,
                        "name": name
                    })
        except Exception as e:
            print(f"Error reading {db_path}: {e}")
    
    # Sort by timestamp descending
    entries.sort(key=lambda x: x['timestamp'] if x['timestamp'] else '', reverse=True)
    
    # Apply overall limit
    if limit:
        entries = entries[:int(limit)]
    
    return entries

def get_all_logs(month=None, limit=100):
    """Get system logs from database for audit log."""
    logs = []
    
    if month:
        year, mon = month.split('-')
        db_path = os.path.join(DB_DIR, f"logs-{year}-{mon}.db")
    else:
        db_path = get_monthly_db_path('logs')
    
    if not os.path.exists(db_path):
        return logs
    
    try:
        with get_db_connection(db_path) as conn:
            query = f"SELECT * FROM logs ORDER BY TIMESTAMP DESC LIMIT {int(limit)}"
            rows = conn.execute(query).fetchall()
            
            for row in rows:
                logs.append({
                    "cuidv2": row['CUIDV2'],
                    "log": row['LOG'],
                    "student_id": row['STUDENT_ID'],
                    "timestamp": row['TIMESTAMP']
                })
    except Exception as e:
        print(f"Error reading logs: {e}")
    
    return logs

def get_all_students():
    """Get all students from database for audit log."""
    students = []
    
    try:
        with get_db_connection(STUDENTS_DB) as conn:
            rows = conn.execute("SELECT * FROM students ORDER BY ID").fetchall()
            for row in rows:
                students.append({
                    "ID": row['ID'],
                    "NAME": row['NAME']
                })
    except Exception as e:
        print(f"Error reading students: {e}")
    
    return students

def get_database_files():
    """Get list of all database files with metadata."""
    files = []
    
    try:
        for filename in os.listdir(DB_DIR):
            if filename.endswith('.db'):
                filepath = os.path.join(DB_DIR, filename)
                stat = os.stat(filepath)
                files.append({
                    "name": filename,
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })
        
        # Sort by modified time descending
        files.sort(key=lambda x: x['modified'], reverse=True)
    except Exception as e:
        print(f"Error listing database files: {e}")
    
    return files

def get_stats():
    """Get statistics for audit log dashboard."""
    stats = {
        "today_total": 0,
        "month_in": 0,
        "month_out": 0,
        "month_logs": 0
    }
    
    now = datetime.datetime.now()
    today_date = now.strftime('%Y-%m-%d')
    
    # Count today's entries and month totals
    for direction in ['in', 'out']:
        db_path = get_monthly_db_path(direction)
        if not os.path.exists(db_path):
            continue
            
        try:
            with get_db_connection(db_path) as conn:
                # Month total
                month_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                stats[f'month_{direction}'] = month_count
                
                # Today's count
                today_count = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE date(TIMESTAMP) = ?",
                    (today_date,)
                ).fetchone()[0]
                stats['today_total'] += today_count
        except Exception as e:
            print(f"Error getting stats for {direction}: {e}")
    
    # Count logs
    logs_path = get_monthly_db_path('logs')
    if os.path.exists(logs_path):
        try:
            with get_db_connection(logs_path) as conn:
                stats['month_logs'] = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        except Exception as e:
            print(f"Error getting log stats: {e}")
    
    return stats

# Initialize on load
init_students_db()