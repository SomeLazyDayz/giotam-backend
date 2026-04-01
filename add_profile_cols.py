import sqlite3

def add_columns():
    conn = sqlite3.connect('instance/blood.db') # Or just blood.db, depending on Flask SQLite config
    cursor = conn.cursor()
    
    columns = [
        ('dob', 'VARCHAR(20)'),
        ('gender', 'VARCHAR(10)'),
        ('weight', 'VARCHAR(10)'),
        ('height', 'VARCHAR(10)')
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};")
            print(f"Added column {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"Column {col_name} already exists.")
            else:
                print(f"Error adding {col_name}: {e}")
                
    conn.commit()
    conn.close()

if __name__ == "__main__":
    # We should also check just `blood.db` in the root folder because we see it's fallback.
    try:
        add_columns()
    except sqlite3.OperationalError:
        # Retry with the exact path if instance/blood.db fails
        conn = sqlite3.connect('blood.db')
        cursor = conn.cursor()
        
        columns = [
            ('dob', 'VARCHAR(20)'),
            ('gender', 'VARCHAR(10)'),
            ('weight', 'VARCHAR(10)'),
            ('height', 'VARCHAR(10)')
        ]
        
        for col_name, col_type in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};")
                print(f"Added column {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"Column {col_name} already exists.")
                else:
                    print(f"Error adding {col_name}: {e}")
                    
        conn.commit()
        conn.close()
