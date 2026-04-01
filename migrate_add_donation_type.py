"""
Script migration: Thêm cột donation_type vào bảng donation_records
Chạy một lần duy nhất để cập nhật database hiện có.
"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'blood.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Kiểm tra xem cột đã tồn tại chưa
cursor.execute("PRAGMA table_info(donation_records)")
columns = [row[1] for row in cursor.fetchall()]
print("Các cột hiện tại:", columns)

if 'donation_type' not in columns:
    cursor.execute("ALTER TABLE donation_records ADD COLUMN donation_type TEXT")
    conn.commit()
    print("✅ Đã thêm cột donation_type thành công!")
else:
    print("ℹ️  Cột donation_type đã tồn tại, không cần thêm nữa.")

conn.close()
