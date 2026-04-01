
import sqlite3
import os

db_path = 'd:/Downloads/HK1 2025-2026 Minh Tuấn/Code/backend/instance/blood.db'
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    # Try alternate path
    db_path = 'd:/Downloads/HK1 2025-2026 Minh Tuấn/Code/backend/blood.db'

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("--- Donation Records ---")
    cursor.execute("SELECT * FROM donation_records")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
        
    print("\n--- Users (First 5) ---")
    cursor.execute("SELECT id, name, email, role FROM users LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
    
    conn.close()
else:
    print(f"DB still not found at {db_path}")
