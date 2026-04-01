from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(
            name='Admin', 
            email='admin@giotam.com', 
            phone='0123456789', 
            password=generate_password_hash('admin'), 
            role='admin', 
            address='BV Đà Nẵng'
        )
        db.session.add(admin)
        db.session.commit()
        print('✅ Đã tạo tài khoản admin thành công!')
    else:
        print('⚠️ Tài khoản admin đã tồn tại.')