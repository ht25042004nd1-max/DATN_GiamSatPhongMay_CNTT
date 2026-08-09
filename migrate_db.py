import sqlite3

def add_columns():
    db_path = 'database/lab_monitor.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE computers ADD COLUMN last_seen DATETIME;")
        print("Added last_seen")
    except Exception as e:
        print(f"Error adding last_seen: {e}")
        
    try:
        cursor.execute("ALTER TABLE computers ADD COLUMN last_ping_ms INTEGER;")
        print("Added last_ping_ms")
    except Exception as e:
        print(f"Error adding last_ping_ms: {e}")
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    add_columns()
