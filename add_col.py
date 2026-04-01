import sqlite3

def add_column():
    conn = sqlite3.connect('instance/blood.db')
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE blood_requests ADD COLUMN donation_type VARCHAR(50) DEFAULT 'Toàn phần'")
        print("Column donation_type added successfully!")
    except Exception as e:
        print(f"Error (maybe column exists): {e}")
    finally:
        conn.commit()
        conn.close()

if __name__ == '__main__':
    add_column()
