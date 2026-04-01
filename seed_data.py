from datetime import datetime
from app import app, db, User, Hospital
from werkzeug.security import generate_password_hash

def seed_database():
    """Xóa, tạo mới, và nạp duy nhất dữ liệu Bệnh Viện Đà Nẵng."""
    with app.app_context():
        print("--- Bắt đầu quá trình Nạp Dữ Liệu vào Database ---")
        db.drop_all()
        db.create_all()
        
        print("\n🏥 Đang thêm cơ sở bệnh viện...")
        hospital_data = {"name": "Bệnh viện Đà Nẵng", "lat": 16.072717, "lng": 108.215678}
        db.session.add(Hospital(**hospital_data))
        print(" -> Xong.")

        print("\n👨‍⚕️ Đang tạo tài khoản Bệnh viện Đà Nẵng...")
        hospital_user = User(
            name="Bệnh viện Đà Nẵng",
            phone="0236 3821 118",
            email="benhviendanang@gmail.com",
            password=generate_password_hash("benhviendanang"),
            role="hospital",
            address="124 Hải Phòng, Thạch Thang, Hải Châu, Đà Nẵng",
            lat=16.072717,
            lng=108.215678,
            blood_type='O+',
            last_donation=None
        )
        db.session.add(hospital_user)
        print(" -> Xong tài khoản bệnh viện.")

        db.session.commit()
        print("\n--- Nạp Dữ Liệu Hoàn Tất! ---")
        print("✅ Đã tạo duy nhất tài khoản và cơ sở cho Bệnh viện Đà Nẵng.")
        print("--------------------------")

if __name__ == '__main__':
    seed_database()
