import os
import secrets
import smtplib  # Thư viện gửi mail
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
from flask_cors import CORS
from dateutil.parser import parse
from werkzeug.security import generate_password_hash, check_password_hash

# Import geocoding MIỄN PHÍ (File geocoding_free.py phải nằm cùng thư mục)
from geocoding_free import geocode_address

# --- FIREBASE ADMIN SDK (Push Notification) ---
try:
    import json
    import firebase_admin
    from firebase_admin import credentials, messaging

    if not firebase_admin._apps:  # Tránh khởi tạo nhiều lần khi Flask reload
        # Ưu tiên 1: Đọc từ biến môi trường (dùng khi deploy lên Render/production)
        _firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
        if _firebase_creds_json:
            _creds_dict = json.loads(_firebase_creds_json)
            cred = credentials.Certificate(_creds_dict)
            print("✅ Firebase: Đọc credentials từ biến môi trường.")
        else:
            # Ưu tiên 2: Đọc từ file JSON (dùng khi dev local)
            _SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(__file__), 'firebase_service_account.json')
            if os.path.exists(_SERVICE_ACCOUNT_PATH):
                cred = credentials.Certificate(_SERVICE_ACCOUNT_PATH)
                print("✅ Firebase: Đọc credentials từ file local.")
            else:
                raise FileNotFoundError(
                    "Không tìm thấy Firebase credentials. "
                    "Hãy set biến môi trường FIREBASE_CREDENTIALS hoặc đặt file firebase_service_account.json vào thư mục backend."
                )
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin SDK khởi tạo thành công!")

    FCM_ENABLED = True
except Exception as _fcm_err:
    print(f"⚠️ Firebase Admin SDK không khởi tạo được: {_fcm_err}")
    print("   → Gửi email vẫn hoạt động, push notification bị TẮT.")
    FCM_ENABLED = False

# --- KHỞI TẠO VÀ CẤU HÌNH ---
app = Flask(__name__)
# Cấu hình CORS - liệt kê rõ các domain được phép gọi API (từ ver 2)
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://localhost:3001",
    "https://giotam.vercel.app",
    "https://giotam-re7l.vercel.app",
    "https://giotam-frontend-xi.vercel.app",
    "https://giotam-mobile-henna.vercel.app",
    "*" # Phòng ngừa mobile app gặp lỗi CORS khi chạy Capacitor localhost
]
cors = CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- DATABASE ---
# Ưu tiên dùng DATABASE_URL từ môi trường (Render.com cung cấp)
# Nếu không có thì fallback về SQLite cho dev local
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Render cung cấp URL dạng postgres:// nhưng SQLAlchemy cần postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

if DATABASE_URL:
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
else:
    # Local development - dùng SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blood.db'
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {
            'timeout': 30,
            'check_same_thread': False
        },
        'pool_pre_ping': True,
        'pool_recycle': 3600,
    }

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# --- CẤU HÌNH EMAIL HỆ THỐNG ---
# Đã điền sẵn thông tin của bạn
SENDER_EMAIL = "minhtuandoanxxx@gmail.com"
APP_PASSWORD = "mavn ohfr xwtz cvgg"

# URL frontend (dùng trong link email ẩn danh)
FRONTEND_BASE_URL = os.environ.get('FRONTEND_URL', 'https://giotam.vercel.app')
# URL backend (dùng cho link /set_anonymous)
BACKEND_BASE_URL = os.environ.get('BACKEND_URL', 'https://giotam-backend.onrender.com')

# URL công khai của server (ngrok hoặc IP thực).
# Thay đổi dòng này thành ngrok URL của bạn khi dùng điện thoại thực.
BASE_URL = "https://arletta-unfavoured-immemorially.ngrok-free.dev"  # ngrok URL của bạn


# --- MODELS (CƠ SỞ DỮ LIỆU) ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default='')
    phone = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='donor')
    address = db.Column(db.String(200), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    blood_type = db.Column(db.String(5), nullable=True)
    dob = db.Column(db.String(20), nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    weight = db.Column(db.String(10), nullable=True)
    height = db.Column(db.String(10), nullable=True)
    last_donation = db.Column(db.Date, nullable=True)
    donations_count = db.Column(db.Integer, default=0)
    reward_points = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hide_name = db.Column(db.Boolean, default=False)
    donation_records = db.relationship('DonationRecord', backref='user', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'role': self.role,
            'address': self.address,
            'lat': self.lat,
            'lng': self.lng,
            'blood_type': self.blood_type,
            'dob': self.dob,
            'gender': self.gender,
            'weight': self.weight,
            'height': self.height,
            'last_donation': self.last_donation.isoformat() if self.last_donation else None,
            'donations_count': self.donations_count,
            'reward_points': self.reward_points,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'hide_name': self.hide_name
        }

class Hospital(db.Model):
    __tablename__ = 'hospitals'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)

    def to_dict(self):
         return {'id': self.id, 'name': self.name, 'lat': self.lat, 'lng': self.lng }

class DonationRecord(db.Model):
    __tablename__ = 'donation_records'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    donation_date = db.Column(db.Date, nullable=False)
    amount_ml = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='completed')
    donation_type = db.Column(db.String(50), nullable=True) # Loại hiến (Toàn phần, Tiểu cầu, v.v.)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)  # True = ẩn danh trên FB
    anonymous_token = db.Column(db.String(64), nullable=True)  # Token xác thực link email

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'donation_date': self.donation_date.isoformat() if self.donation_date else None,
            'amount_ml': self.amount_ml,
            'status': self.status,
            'donation_type': self.donation_type,
            'is_anonymous': self.is_anonymous
        }

class BloodRequest(db.Model):
    __tablename__ = 'blood_requests'
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False)
    amount_ml = db.Column(db.Integer, nullable=False, default=350)
    urgency = db.Column(db.String(20), nullable=False, default='Cần gấp')  # 'Cần gấp', 'Khẩn cấp', 'Thường'
    address = db.Column(db.String(200), nullable=True)  # Địa chỉ bệnh viện
    note = db.Column(db.Text, nullable=True)
    expected_date = db.Column(db.String(20), nullable=True)
    expiration_date = db.Column(db.String(20), nullable=True)
    time_slot = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='open')  # 'open', 'closed'
    donation_type = db.Column(db.String(50), nullable=True, default='Toàn phần')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hospital = db.relationship('User', foreign_keys=[hospital_id])
    registrations = db.relationship('DonationRegistration', backref='blood_request', lazy=True)

    def to_dict(self):
        hospital = self.hospital
        return {
            'id': self.id,
            'hospital_id': self.hospital_id,
            'hospital_name': hospital.name if hospital else 'Không rõ',
            'hospital_address': self.address or (hospital.address if hospital else ''),
            'blood_type': self.blood_type,
            'amount_ml': self.amount_ml,
            'urgency': self.urgency,
            'note': self.note,
            'expected_date': self.expected_date,
            'expiration_date': self.expiration_date,
            'time_slot': self.time_slot,
            'status': self.status,
            'donation_type': self.donation_type,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'registration_count': len(self.registrations)
        }

class DonationRegistration(db.Model):
    __tablename__ = 'donation_registrations'
    id = db.Column(db.Integer, primary_key=True)
    blood_request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id'), nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    time_slot = db.Column(db.String(100), nullable=False)  # Khầu giờ hiến máu
    status = db.Column(db.String(20), nullable=False, default='registered')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    donor = db.relationship('User', foreign_keys=[donor_id])

    def to_dict(self):
        donor = self.donor
        return {
            'id': self.id,
            'blood_request_id': self.blood_request_id,
            'donor_id': self.donor_id,
            'donor_name': donor.name if donor else 'Không rõ',
            'donor_phone': donor.phone if donor else '',
            'donor_blood_type': donor.blood_type if donor else '',
            'time_slot': self.time_slot,
            'status': self.status,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None
        }

# --- MODEL: LƯU FCM PUSH TOKEN ---
class PushToken(db.Model):
    __tablename__ = 'push_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(500), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<PushToken user={self.user_id}>'



# --- HÀM GỬI EMAIL CẢM ƠN SAU HIẾN MÁU ---
def send_thank_you_email(user_email: str, user_name: str, record_id: int, token: str):
    """Gửi email cảm ơn tình nguyện viên sau khi bệnh viện xác nhận hoàn tất.
    Chạy trong background thread để không block response."""
    with app.app_context():
        try:
            anonymous_link = f"{BACKEND_BASE_URL}/set_anonymous?record_id={record_id}&token={token}"
            
            html_body = f"""
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f9f5f0; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #930511, #c0392b); padding: 40px 32px; text-align: center; }}
    .header h1 {{ color: #fff; margin: 0; font-size: 26px; letter-spacing: 1px; }}
    .header p {{ color: rgba(255,255,255,0.85); margin: 8px 0 0; font-size: 14px; }}
    .body {{ padding: 36px 32px; color: #333; line-height: 1.7; }}
    .body h2 {{ color: #930511; font-size: 20px; margin-bottom: 8px; }}
    .body p {{ margin: 0 0 16px; }}
    .divider {{ border: none; border-top: 2px dashed #f0d6d6; margin: 28px 0; }}
    .notice-box {{ background: #fff8f0; border-left: 4px solid #e67e22; border-radius: 8px; padding: 20px 24px; margin: 24px 0; }}
    .notice-box p {{ margin: 0 0 8px; font-size: 15px; }}
    .btn-anon {{ display: inline-block; margin-top: 16px; background: #930511; color: #fff !important; text-decoration: none; padding: 14px 32px; border-radius: 50px; font-weight: bold; font-size: 16px; letter-spacing: 0.5px; box-shadow: 0 4px 12px rgba(147,5,17,0.3); }}
    .btn-anon:hover {{ background: #7a0410; }}
    .footer {{ background: #f2f2f2; text-align: center; padding: 20px; font-size: 12px; color: #999; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>🩸 Giọt Ấm</h1>
      <p>Kết nối yêu thương — Lan tỏa sự sống</p>
    </div>
    <div class="body">
      <h2>Cảm ơn bạn, {user_name}! 💙</h2>
      <p>
        Thay mặt đội ngũ <strong>Dự Án Giọt Ấm</strong> và <strong>Bệnh viện Đà Nẵng</strong>,
        chúng tôi xin gửi đến bạn lời cảm ơn chân thành và sâu sắc nhất vì đã dành thời gian 
        đến hiến máu hôm nay.
      </p>
      <p>
        Món quà của bạn — những giọt máu quý giá — có thể trực tiếp cứu sống một mạng người. 
        Đây là hành động đẹp đẽ và ý nghĩa mà không phải ai cũng dám làm. Chúng tôi thật sự 
        rất biết ơn sự đóng góp của bạn cho cộng đồng.
      </p>
      <p>
        Bạn sẽ nhận được <strong>giấy chứng nhận tình nguyện hiến máu</strong> từ Bệnh viện Đà Nẵng 
        trong thời gian sớm nhất.
      </p>

      <hr class="divider" />

      <div class="notice-box">
        <p><strong>📢 Thông báo về bài đăng Facebook</strong></p>
        <p>
          Chúng tôi sẽ đăng lời tri ân kèm giấy chứng nhận lên nhóm Facebook
          <strong>"Dự Án Giọt Ấm"</strong> với <strong>tên thật của bạn</strong>.
        </p>
        <p>
          Nếu bạn <strong>không muốn công khai tên thật</strong>, hãy nhấn nút bên dưới —
          chúng tôi sẽ chỉ hiển thị mã tình nguyện viên của bạn.
          Nếu bạn không nhấn, chúng tôi hiểu rằng bạn đồng ý công khai tên. 🙏
        </p>
        <a href="{anonymous_link}" class="btn-anon">🔒 Tôi muốn ẩn danh</a>
      </div>

      <p style="font-size:13px; color:#999; margin-top:24px;">
        (Bạn có thể nhấn nút bất cứ lúc nào, link không có thời hạn.)
      </p>
    </div>
    <div class="footer">
      © 2026 Giọt Ấm · Bệnh viện Đà Nẵng · 124 Hải Phòng, Đà Nẵng<br/>
      Email này được gửi tự động, vui lòng không trả lời.
    </div>
  </div>
</body>
</html>
"""
            msg = MIMEMultipart('alternative')
            msg['From'] = SENDER_EMAIL
            msg['To'] = user_email
            msg['Subject'] = f'🩸 Cảm ơn bạn đã hiến máu, {user_name}! — Giọt Ấm'

            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=15) as server:
                server.login(SENDER_EMAIL, APP_PASSWORD)
                server.sendmail(SENDER_EMAIL, user_email, msg.as_string())
            print(f"✅ Gửi email cảm ơn thành công → {user_email}")
        except Exception as e:
            print(f"⚠️ Lỗi gửi email cảm ơn tới {user_email}: {e}")


# --- ROUTE: NHẬN PHẢN HỒI ẨN DANH QUA LINK EMAIL ---
@app.route('/set_anonymous', methods=['GET'])
def set_anonymous():
    """Tình nguyện viên bấm link trong email để chọn ẩn danh trên Facebook."""
    record_id = request.args.get('record_id', type=int)
    token = request.args.get('token', '')

    if not record_id or not token:
        return "<h2 style='font-family:Arial;color:#930511'>❌ Link không hợp lệ.</h2>", 400

    record = db.session.get(DonationRecord, record_id)
    if not record or not record.anonymous_token or record.anonymous_token != token:
        return "<h2 style='font-family:Arial;color:#930511'>❌ Link không hợp lệ hoặc đã được xử lý.</h2>", 400

    try:
        record.is_anonymous = True
        db.session.commit()
        return """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Giọt Ấm — Đã ghi nhận ẩn danh</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',Arial,sans-serif;background:#FBF2E1;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px}}
    .wrapper{{width:100%;max-width:480px}}
    .header{{background:linear-gradient(135deg,#930511,#c0392b);border-radius:20px 20px 0 0;padding:32px 24px;text-align:center}}
    .header-logo{{font-size:32px;margin-bottom:6px}}
    .header h1{{color:#fff;font-size:22px;font-weight:800;letter-spacing:1px}}
    .header p{{color:rgba(255,255,255,0.8);font-size:13px;margin-top:4px}}
    .card{{background:#fff;border-radius:0 0 20px 20px;padding:40px 32px;text-align:center;box-shadow:0 12px 40px rgba(147,5,17,0.15)}}
    .icon-wrap{{width:80px;height:80px;background:linear-gradient(135deg,#930511,#e74c3c);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;box-shadow:0 6px 20px rgba(147,5,17,0.35)}}
    .icon-wrap svg{{width:40px;height:40px;stroke:#fff;stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round}}
    h2{{color:#930511;font-size:22px;font-weight:800;margin-bottom:12px}}
    .desc{{color:#555;font-size:15px;line-height:1.7;margin-bottom:8px}}
    .desc strong{{color:#222}}
    .divider{{border:none;border-top:2px dashed #f0d6d6;margin:24px 0}}
    .badge{{display:inline-flex;align-items:center;gap:8px;background:#fff0f0;border:2px solid #f5c6c6;color:#930511;font-weight:700;font-size:14px;padding:10px 24px;border-radius:50px;margin-top:8px}}
    .footer-note{{margin-top:24px;font-size:12px;color:#bbb;line-height:1.6}}
    .back-btn{{display:inline-block;margin-top:24px;background:#930511;color:#fff;text-decoration:none;padding:12px 32px;border-radius:50px;font-weight:700;font-size:14px;box-shadow:0 4px 12px rgba(147,5,17,0.3);transition:background .2s}}
    .back-btn:hover{{background:#7a0410}}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <div class="header-logo">🩸</div>
      <h1>Giọt Ấm</h1>
      <p>Kết nối yêu thương — Lan tỏa sự sống</p>
    </div>
    <div class="card">
      <div class="icon-wrap">
        <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
      </div>
      <h2>Đã ghi nhận yêu cầu!</h2>
      <p class="desc">Trên bài đăng Facebook của nhóm <strong>Dự Án Giọt Ấm</strong>, chúng tôi sẽ chỉ hiển thị <strong>mã tình nguyện viên</strong> thay vì tên thật của bạn.</p>
      <hr class="divider"/>
      <p class="desc">Cảm ơn bạn đã tin tưởng và đồng hành cùng chúng tôi. Hành động của bạn hôm nay thật sự rất có ý nghĩa! 💙</p>
      <div class="badge">🔒 Ẩn danh đã được kích hoạt</div>
      <p class="footer-note">Bệnh viện Đà Nẵng · 124 Hải Phòng, Thạch Thang, Hải Châu, Đà Nẵng<br/>© 2026 Dự Án Giọt Ấm</p>
    </div>
  </div>
</body>
</html>""", 200
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi set_anonymous: {e}")
        return """<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"/><style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#FBF2E1;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#fff;border-radius:20px;padding:40px 32px;text-align:center;max-width:400px;box-shadow:0 8px 32px rgba(0,0,0,0.1)}}
h2{{color:#930511;margin-bottom:12px}}p{{color:#666}}
</style></head><body>
<div class="card"><div style="font-size:48px;margin-bottom:16px">❌</div>
<h2>Lỗi hệ thống</h2><p>Vui lòng thử lại sau.</p></div>
</body></html>""", 500


# --- CÁC API ROUTE CƠ BẢN ---

@app.route('/')
def index():
    return jsonify({'message': 'Blood Donation API is running!'})

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify({'count': len(users), 'users': [user.to_dict() for user in users]})

@app.route('/hospitals', methods=['GET'])
def get_hospitals():
    hospitals = Hospital.query.all()
    return jsonify({'count': len(hospitals), 'hospitals': [h.to_dict() for h in hospitals]})

@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        # Lấy top 5 donors có donations_count cao nhất
        top_donors = User.query.filter_by(role='donor').order_by(
            User.donations_count.desc(), 
            User.reward_points.desc()
        ).limit(5).all()
        
        return jsonify({
            'count': len(top_donors),
            'leaderboard': [
                {
                    'id': d.id,
                    'name': f"Người ẩn danh (HD2026-{str(d.id).zfill(5)})" if getattr(d, 'hide_name', False) else d.name,
                    'donations_count': d.donations_count,
                    'reward_points': d.reward_points,
                    'blood_type': d.blood_type
                } for d in top_donors
            ]
        }), 200
    except Exception as e:
        print(f"Lỗi Leaderboard: {e}")
        return jsonify({'error': 'Lỗi lấy bảng vinh danh'}), 500

@app.route('/api/users/<int:user_id>/privacy', methods=['POST'])
@app.route('/users/<int:user_id>/privacy', methods=['POST']) # Hỗ trợ cả hai phòng trường hợp config thiếu
def update_user_privacy(user_id):
    try:
        data = request.get_json()
        hide_name = data.get('hide_name', False)
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'Không tìm thấy người dùng'}), 404
            
        user.hide_name = hide_name
        db.session.commit()
        return jsonify({'message': 'Đã cập nhật cấu hình', 'user': user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi khi update privacy: {e}")
        return jsonify({'error': 'Lỗi máy chủ'}), 500

# --- ĐĂNG KÝ & ĐĂNG NHẬP ---

@app.route('/register_donor', methods=['POST'])
def register_donor():
    data = request.get_json()

    # Validate thông tin
    required_fields = ['fullName', 'email', 'phone', 'password', 'address', 'bloodType', 'dob', 'gender', 'weight', 'height']
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({'error': 'Thiếu thông tin bắt buộc hoặc thông tin rỗng'}), 400

    # Kiểm tra trùng lặp
    if User.query.filter((User.email == data['email']) | (User.phone == data['phone'])).first():
         return jsonify({'error': 'Email hoặc số điện thoại đã tồn tại'}), 409

    # Xử lý địa chỉ -> tọa độ (Geocoding)
    address = data['address']
    lat, lng = None, None
    try:
        coords = geocode_address(address)
        if coords:
            lat, lng = coords
            print(f"✅ Geocoding thành công: {lat}, {lng}")
        else:
            print(f"⚠️ Không tìm thấy tọa độ cho '{address}'")
    except Exception as e:
        print(f"❌ Lỗi geocoding: {e}")

    # Xử lý ngày hiến máu
    last_donation_date = None
    if data.get('lastDonationDate'):
        date_str = data['lastDonationDate']
        if date_str:
            try:
                last_donation_date = parse(date_str).date()
            except (ValueError, TypeError):
                 return jsonify({'error': 'Định dạng ngày không hợp lệ'}), 400

    blood_type = data.get('bloodType', '')
    if len(blood_type) > 5:
        # Nếu gửi lên "Chưa biết" (9 ký tự) thì đổi thành "Khác"
        if blood_type == "Chưa biết":
            blood_type = "Khác"
        else:
            blood_type = blood_type[:5]

    # Tạo user mới
    new_user = User(
        name=data['fullName'],
        email=data['email'],
        phone=data['phone'],
        password=generate_password_hash(data['password']), 
        role='donor',
        address=address,
        lat=lat,
        lng=lng,
        blood_type=blood_type,
        dob=data.get('dob'),
        gender=data.get('gender'),
        weight=data.get('weight'),
        height=data.get('height'),
        last_donation=last_donation_date
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        user_dict = new_user.to_dict()
        
        msg = 'Đăng ký thành công'
        if lat is None:
             msg += ' (nhưng chưa xác định được tọa độ)'
        
        return jsonify({'message': msg, 'user': user_dict}), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi DB: {e}")
        return jsonify({'error': 'Lỗi máy chủ nội bộ'}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Thiếu email hoặc mật khẩu'}), 400
    
    user = User.query.filter_by(email=data['email']).first()
    
    if user:
        if check_password_hash(user.password, data['password']):
            return jsonify({'message': 'Đăng nhập thành công', 'user': user.to_dict()}), 200
        elif user.password == data['password']:
            # Fallback với mật khẩu cũ chưa mã hóa
            user.password = generate_password_hash(data['password'])
            db.session.commit()
            return jsonify({'message': 'Đăng nhập thành công', 'user': user.to_dict()}), 200

    # Trả về 401 để Frontend bắt lỗi hiển thị bảng đỏ
    return jsonify({'error': 'Email hoặc mật khẩu không chính xác'}), 401


# --- TÍNH NĂNG LỌC TÌNH NGUYỆN VIÊN (AI FILTER) ---

@app.route('/create_alert', methods=['POST'])
def create_alert():
    data = request.get_json()
    
    if not data.get('hospital_id') or not data.get('blood_type'):
        return jsonify({'error': 'Thiếu thông tin bệnh viện hoặc nhóm máu'}), 400
        
    # Tìm bệnh viện từ bảng users (role='hospital')
    hospital_user = User.query.filter_by(id=data['hospital_id'], role='hospital').first()
    # Nếu không tìm thấy, thử admin (để admin cũng có thể test)
    if not hospital_user:
        hospital_user = User.query.filter_by(id=data['hospital_id']).first()
    if not hospital_user:
        return jsonify({'error': 'Không tìm thấy bệnh viện'}), 404

    # Tạo object tương thích với ai_filter (cần lat, lng, name)
    class HospitalProxy:
        def __init__(self, user):
            self.id = user.id
            self.name = user.name
            self.lat = user.lat or 16.0544068  # Default: Đà Nẵng
            self.lng = user.lng or 108.2021667
        def to_dict(self):
            return {'id': self.id, 'name': self.name, 'lat': self.lat, 'lng': self.lng}

    hospital = HospitalProxy(hospital_user)
        
    blood_type_needed = data['blood_type']
    radius_km = data.get('radius_km', 10)
    
    # Lấy danh sách donor phù hợp sơ bộ (cùng nhóm máu)
    # Không yêu cầu lat/lng để không bỏ sót donor chưa có tọa độ
    suitable_users = User.query.filter(
        User.role == 'donor',
        User.blood_type == blood_type_needed
    ).all()

    # Thử geocode cho donor chưa có tọa độ
    for u in suitable_users:
        if u.lat is None and u.address:
            try:
                coords = geocode_address(u.address)
                if coords:
                    u.lat, u.lng = coords
                    db.session.commit()
            except Exception:
                pass
    
    try:
        # Gọi thuật toán lọc (file ai_filter.py)
        from ai_filter import filter_nearby_users
        results = filter_nearby_users(hospital, suitable_users, radius_km)
        
        # Lấy top 50
        top_50_users = results[:50]
        
        return jsonify({
            'hospital': hospital.to_dict(),
            'blood_type_needed': blood_type_needed,
            'total_matched': len(results),
            'top_50_users': [
                {
                    'user': r['user'].to_dict(), 
                    'distance_km': r['distance'], 
                    'ai_score': r['ai_score'],
                    'is_eligible': r.get('is_eligible', True),
                    'recovery_days_left': r.get('recovery_days_left', 0)
                }
                for r in top_50_users
            ]
        })
    except ImportError:
        return jsonify({'error': "Thiếu file ai_filter.py"}), 500
    except Exception as e:
        print(f"Lỗi AI Filter: {e}")
        return jsonify({'error': 'Lỗi xử lý lọc người dùng'}), 500


@app.route('/users/<int:user_id>', methods=['PUT', 'PATCH'])
@app.route('/api/users/<int:user_id>/profile', methods=['PUT'])
def update_user_profile(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    allowed_fields = ['name', 'phone', 'address', 'blood_type', 'last_donation', 'lat', 'lng', 'reward_points', 'dob', 'gender', 'weight', 'height']
    
    geocoding_needed = False
    old_address = user.address
    
    for field in allowed_fields:
        if field in data:
            if field == 'last_donation':
                if data[field]:
                    try:
                        setattr(user, field, parse(data[field]).date())
                    except: pass
                else:
                     setattr(user, field, None)
            else:
                 setattr(user, field, data[field])
            
            if field == 'address' and data[field] != old_address:
                geocoding_needed = True

    if geocoding_needed and user.address:
        try:
            coords = geocode_address(user.address)
            if coords:
                user.lat, user.lng = coords
        except Exception: pass

    try:
        db.session.commit()
        return jsonify({'message': 'Cập nhật thành công', 'user': user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Lỗi cập nhật'}), 500

@app.route('/users/<int:user_id>/change-password', methods=['POST'])
def change_password(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({'error': 'Vui lòng cung cấp mật khẩu cũ và mới'}), 400
        
    if not check_password_hash(user.password, old_password) and user.password != old_password:
        return jsonify({'error': 'Mật khẩu cũ không chính xác'}), 401
        
    try:
        user.password = generate_password_hash(new_password)
        db.session.commit()
        return jsonify({'message': 'Đổi mật khẩu thành công'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Lỗi rerver khi đổi mật khẩu'}), 500

@app.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        # Xóa các record liên quan trước (DonationRecord)
        DonationRecord.query.filter_by(user_id=user_id).delete()
        
        db.session.delete(user)
        db.session.commit()
        return jsonify({'message': 'Đã xóa tài khoản thành công'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Lỗi server khi xóa tài khoản'}), 500

@app.route('/users/<int:user_id>/history', methods=['GET'])
def get_user_donation_history(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Không tìm thấy người dùng'}), 404
        
    records = DonationRecord.query.filter_by(user_id=user_id).order_by(DonationRecord.donation_date.desc()).all()
    return jsonify({
        'count': len(records),
        'history': [r.to_dict() for r in records]
    }), 200

# --- HELPER: KIỂM TRA ĐỦ ĐIỀU KIỆN THỜI GIAN HIẾN MÁU ---
def check_donation_eligibility(user_id):
    """
    Kiểm tra thời gian nghỉ giữa 2 lần hiến máu.
    - Máu toàn phần: Tối thiểu 84 ngày (12 tuần).
    - Thành phần máu (Tiểu cầu/Huyết tương): Tối thiểu 14 ngày (2 tuần).
    Trả về bộ tuple: (is_eligible: bool, error_message: str|None)
    """
    last_record = DonationRecord.query.filter_by(
        user_id=user_id, status='completed'
    ).order_by(DonationRecord.donation_date.desc()).first()

    if not last_record or not last_record.donation_date:
        return True, None

    days_passed = (datetime.now().date() - last_record.donation_date).days

    donation_type = last_record.donation_type or 'Toàn phần'
    if 'Toàn phần' in donation_type:
        required_days = 84
    else:
        required_days = 14

    if days_passed < required_days:
        remaining = required_days - days_passed
        return False, f"Bạn cần nghỉ thêm {remaining} ngày nữa mới đủ điều kiện (lần gần nhất hiến '{donation_type}' vào {last_record.donation_date.strftime('%d/%m/%Y')})."

    return True, None


# --- ĐĂNG KÝ FCM PUSH TOKEN ---
@app.route('/register_push_token', methods=['POST'])
def register_push_token():
    data = request.get_json()
    user_id = data.get('user_id')
    token = data.get('token')

    if not user_id or not token:
        return jsonify({'error': 'Thiếu user_id hoặc token'}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Không tìm thấy user'}), 404

    try:
        existing = PushToken.query.filter_by(token=token).first()
        if existing:
            # Nếu thiết bị này vừa được tài khoản mới đăng nhập, chuyển token sang tài khoản mới
            if existing.user_id != user_id:
                existing.user_id = user_id
                db.session.commit()
                print(f"🔄 Đã cập nhật Push Token sang thiết bị của user {user.name}")
        else:
            new_token = PushToken(user_id=user_id, token=token)
            db.session.add(new_token)
            db.session.commit()
            print(f"✅ Đã lưu push token cho user {user.name}")
            
        return jsonify({'message': 'Token đã được xử lý'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"❌ Lỗi lưu push token: {e}")
        return jsonify({'error': 'Lỗi server'}), 500


# --- GỬI EMAIL/PUSH CHO TÌNH NGUYỆN VIÊN (BACKGROUND THREAD) ---
@app.route('/notify_donors', methods=['POST'])
def notify_donors():
    data = request.get_json()
    raw_donor_ids = data.get('donor_ids')
    message_body = data.get('message')
    hospital_id = data.get('hospital_id')
    blood_type = data.get('blood_type')
    donation_type = data.get('donation_type', 'Toàn phần')

    if not raw_donor_ids or not message_body:
        return jsonify({'error': 'Thiếu ID người nhận hoặc nội dung'}), 400

    # Tạo Yêu cầu Khẩn cấp (BloodRequest) để hiển thị công khai trên ứng dụng (Trang Chủ + Chuông báo)
    if hospital_id and blood_type:
        new_request = BloodRequest(
            hospital_id=hospital_id,
            blood_type=blood_type,
            amount_ml=350,
            urgency='Khẩn cấp',
            status='open',
            donation_type=donation_type,
            expected_date=datetime.now().strftime('%Y-%m-%d'),
            expiration_date=(datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        )
        db.session.add(new_request)

    # Ép kiểu an toàn sang số nguyên để tránh lỗi Database
    donor_ids = [int(i) for i in raw_donor_ids]

    try:
        users_to_notify = User.query.filter(User.id.in_(donor_ids)).all()
        
        # Tạo DonationRecord PENDING đồng bộ trước khi trả response
        for user in users_to_notify:
            if user.email:
                new_pending = DonationRecord(
                    user_id=user.id,
                    donation_date=datetime.now().date(),
                    amount_ml=0,
                    status='pending'
                )
                db.session.add(new_pending)
        db.session.commit()

        # Dữ liệu truyền vào background thread
        # Dùng List Data để tranh bị lỗi session database khi query khác thread
        user_data = [(u.email, u.name, u.blood_type, u.id) for u in users_to_notify if u.email]
        push_donor_ids = donor_ids.copy()

        def send_notifications_background(user_data, push_donor_ids, message_body):
            # Cần chạy app context mớ để có the query PushToken
            with app.app_context():
                success_count = 0
                push_count = 0
                try:
                    print("🔌 Đang kết nối Gmail (SMTP) để gửi nền...")
                    server = smtplib.SMTP('smtp.gmail.com', 587)
                    server.starttls()
                    server.login(SENDER_EMAIL, APP_PASSWORD.replace(" ", ""))
                    print("✅ Kết nối thành công!")

                    for email, name, blood_type, uid in user_data:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = SENDER_EMAIL
                            msg['To'] = email
                            msg['Subject'] = f"🩸 KHẨN CẤP: CẦN MÁU NHÓM {blood_type} - GIỌT ẤM"

                            html_body = f"""
                            <!DOCTYPE html>
                            <html>
                            <head>
                                <style>
                                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f4f4f4; }}
                                    .email-container {{ max-width: 600px; margin: 20px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; }}
                                    .header {{ background-color: #930511; color: #ffffff; padding: 20px; text-align: center; }}
                                    .header h1 {{ margin: 0; }}
                                    .content {{ padding: 25px; }}
                                    .alert-box {{ background-color: #fbe4e6; border-left: 5px solid #930511; padding: 15px; margin: 20px 0; }}
                                    .alert-title {{ color: #930511; font-weight: bold; margin-top: 0; }}
                                    .btn-action {{ display: block; width: 200px; margin: 20px auto; padding: 12px; background-color: #930511; color: white !important; text-align: center; text-decoration: none; border-radius: 50px; font-weight: bold; }}
                                    .footer {{ background-color: #f9f9f9; padding: 15px; text-align: center; font-size: 12px; color: #888; }}
                                </style>
                            </head>
                            <body>
                                <div class="email-container">
                                    <div class="header">
                                        <h1>🩸 GIỌT ẤM</h1>
                                        <p>Kết nối yêu thương - Sẻ chia sự sống</p>
                                    </div>
                                    <div class="content">
                                        <p>Xin chào <strong>{name}</strong>,</p>
                                        <p>Hệ thống <strong>Giọt Ấm</strong> vừa nhận được thông báo khẩn cấp:</p>
                                        <div class="alert-box">
                                            <p class="alert-title">📢 THÔNG BÁO CẦN MÁU</p>
                                            <p>{message_body}</p>
                                        </div>
                                        <p>Sự giúp đỡ của bạn có thể cứu sống một mạng người. Hãy đến bệnh viện sớm nhất nếu có thể.</p>
                                        <a href="{BASE_URL}/participate?user_id={uid}&ngrok-skip-browser-warning=true" class="btn-action" target="_blank">Tôi sẽ tham gia</a>
                                        <p>Trân trọng,<br>Đội ngũ Giọt Ấm</p>
                                    </div>
                                    <div class="footer">
                                        <p>Email tự động từ hệ thống Giọt Ấm.</p>
                                    </div>
                                </div>
                            </body>
                            </html>
                            """
                            msg.attach(MIMEText(html_body, 'html'))
                            server.send_message(msg)
                            print(f"✅ Đã gửi email cho {name} ({email})")
                            success_count += 1
                        except Exception as e:
                            print(f"⚠️ Lỗi gửi email {name}: {e}")

                    server.quit()
                    print("📨 Hoàn tất gửi email background!")

                except Exception as e:
                    print(f"❌ Lỗi Mail background: {e}")

                # Gửi Firebase Push Background
                if FCM_ENABLED:
                    print(f"📲 Bắt đầu gửi push notification (Background)...")
                    for uid in push_donor_ids:
                        tokens = PushToken.query.filter_by(user_id=uid).all()
                        if not tokens:
                            continue
                        
                        user = db.session.get(User, uid)
                        user_name = user.name if user else 'Tình nguyện viên'

                        for pt in tokens:
                            try:
                                msg_fcm = messaging.Message(
                                    notification=messaging.Notification(
                                        title="🩸 KHẨN CẤP: Cần máu - Giọt Ấm",
                                        body=f"Xin chào {user_name}! {message_body[:80]}...",
                                    ),
                                    data={
                                        'type': 'blood_request',
                                        'user_id': str(uid),
                                    },
                                    android=messaging.AndroidConfig(
                                        priority='high',
                                        notification=messaging.AndroidNotification(
                                            sound='default',
                                            channel_id='blood_alert',
                                        )
                                    ),
                                    token=pt.token,
                                )
                                messaging.send(msg_fcm)
                                push_count += 1
                                print(f"  ✅ Push tới {user_name} thành công")
                            except Exception as push_err:
                                print(f"  ⚠️ Push tới {user_name} thất bại: {push_err}")
                                if 'registration-token-not-registered' in str(push_err) or 'Requested entity was not found' in str(push_err):
                                    db.session.delete(pt)
                    try:
                        db.session.commit()
                    except Exception as db_err:
                        db.session.rollback()
                        print(f"⚠️ Lỗi dọn DB FCM Tokens: {db_err}")
                else:
                    print("⚠️ FCM không khả dụng, bỏ qua push notification.")
                
                print(f"🏁 XONG background task: Email: {success_count}, Push: {push_count}.")

        thread = threading.Thread(target=send_notifications_background, args=(user_data, push_donor_ids, message_body), daemon=True)
        thread.start()

        return jsonify({
            'message': f'Đã tạo {len(user_data)} yêu cầu chờ. Email và Push đang được gửi trong nền.',
            'count': len(user_data)
        }), 200

    except Exception as e:
        print(f"❌ Lỗi notify_donors: {e}")
        return jsonify({'error': f'Lỗi hệ thống: {str(e)}'}), 500


# --- XỬ LÝ FORM LIÊN HỆ (GỬI VỀ ADMIN) ---

@app.route('/contact_support', methods=['POST'])
def contact_support():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone')
    message = data.get('message')

    if not all([name, email, phone, message]):
        return jsonify({'error': 'Vui lòng điền đầy đủ thông tin'}), 400

    # Email nhận thư (Gửi về chính Admin)
    RECEIVER_EMAIL = SENDER_EMAIL 

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)

        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"🔔 [LIÊN HỆ] Tin nhắn mới từ {name}"

        body = f"""
        Xin chào Admin Giọt Ấm,

        Bạn có một liên hệ mới từ website:
        ------------------------------------------------
        👤 Người gửi: {name}
        📧 Email: {email}
        📞 SĐT: {phone}
        ------------------------------------------------
        📝 Nội dung tin nhắn:
        {message}
        ------------------------------------------------
        """
        msg.attach(MIMEText(body, 'plain'))

        server.send_message(msg)
        server.quit()

        print(f"✅ Đã nhận liên hệ từ {name}")
        return jsonify({'message': 'Cảm ơn bạn! Chúng tôi đã nhận được tin nhắn.'}), 200

    except Exception as e:
        print(f"❌ Lỗi gửi mail liên hệ: {e}")
        return jsonify({'error': 'Lỗi hệ thống gửi mail'}), 500


# --- XÁC NHẬN THAM GIA TỪ EMAIL ---
@app.route('/participate', methods=['GET'])
def participate():
    raw_user_id = request.args.get('user_id')
    if not raw_user_id:
        return "Thiếu thông tin tình nguyện viên.", 400

    try:
        user_id = int(raw_user_id)
    except ValueError:
        return "Mã tình nguyện viên không hợp lệ.", 400
        
    user = db.session.get(User, user_id)
    if not user:
        return "Không tìm thấy tình nguyện viên.", 404
        
    is_eligible, err_msg = check_donation_eligibility(user.id)
    if not is_eligible:
        html_err = f"""
        <div style="text-align:center; padding:50px; font-family:sans-serif; background:#f9f9f9; height:100vh;">
            <h2 style="color:#930511;">🚫 Không Thể Hiến Máu Lúc Này</h2>
            <p style="color:#333; font-size:18px; max-width:600px; margin:20px auto; background:white; padding:20px; border-radius:10px; box-shadow:0 4px 6px rgba(0,0,0,0.1); border-left:5px solid #930511;">
                {err_msg}
            </p>
            <p>Xin trân trọng cảm ơn tấm lòng nhiệt huyết của bạn, hẹn gặp lại bạn ở các lần hiến máu tiếp theo!</p>
        </div>
        """
        return html_err, 400

    # Tìm record pending gần nhất của user này (vừa được tạo khi gửi mail)
    record = DonationRecord.query.filter_by(user_id=user.id, status='pending').order_by(DonationRecord.id.desc()).first()
    
    if record:
        record.status = 'accepted'
    else:
        # Nếu không thấy (có thể do lỗi db lúc gửi mail), tạo mới với status accepted luôn
        record = DonationRecord(
            user_id=user.id,
            donation_date=datetime.now().date(),
            amount_ml=0,
            status='accepted'
        )
        db.session.add(record)
    
    db.session.commit()
    
    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Xác nhận tham gia</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #f9f9f9; }}
            .container {{ background: white; padding: 30px; border-radius: 10px; max-width: 500px; margin: auto; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            h1 {{ color: #930511; }}
            p {{ font-size: 18px; color: #333; }}
            .success-icon {{ font-size: 50px; color: green; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✔️</div>
            <h1>Cảm ơn bạn, {user.name}!</h1>
            <p>Sự sẵn sàng của bạn là vô giá! Chúng tôi đã ghi nhận phản hồi của bạn.</p>
            <p>Vui lòng di chuyển đến bệnh viện trong thời gian sớm nhất.</p>
            <p style="color: #930511; font-weight: bold;">🎁 Sau khi hiến máu xong và được nhân viên y tế xác nhận, bạn sẽ nhận được <strong>10 điểm thưởng</strong> trong ứng dụng Giọt Ấm.</p>
        </div>
    </body>
    </html>
    """, 200

# --- BLOOD REQUEST APIs (v2) ---

@app.route('/blood-requests', methods=['GET'])
def get_blood_requests():
    """Lấy danh sách yêu cầu hiến máu đang mở. Tình nguyện viên xem ở trang Home."""
    try:
        donor_id = request.args.get('donor_id')
        requests_list = BloodRequest.query.filter_by(status='open').order_by(BloodRequest.created_at.desc()).all()
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        now_dt = datetime.utcnow()
        valid_requests = []
        
        for r in requests_list:
            # 1. Nếu là Khẩn cấp, ẩn bài sau 60 phút
            if r.urgency == 'Khẩn cấp':
                time_diff = now_dt - r.created_at
                if time_diff.total_seconds() > 3600:
                    continue
            else:
                # Chỉ request Thường mới áp dụng check hết hạn expiration_date
                if r.expiration_date and r.expiration_date < today_str:
                    continue

            # 2. Xóa bỏ khỏi danh sách hiển thị nếu donor_id này đã Đăng ký tham gia rồi
            if donor_id:
                has_reg = DonationRegistration.query.filter_by(blood_request_id=r.id, donor_id=donor_id).first()
                if has_reg:
                    continue
                    
            valid_requests.append(r)
                
        return jsonify({
            'count': len(valid_requests),
            'blood_requests': [r.to_dict() for r in valid_requests]
        }), 200
    except Exception as e:
        print(f"Lỗi get_blood_requests: {e}")
        return jsonify({'error': 'Lỗi lấy danh sách yêu cầu hiến máu'}), 500


@app.route('/blood-requests', methods=['POST'])
def create_blood_request():
    """Bệnh viện tạo yêu cầu hiến máu mới."""
    data = request.get_json()
    required = ['hospital_id', 'blood_type', 'amount_ml']
    if not all(f in data and data[f] for f in required):
        return jsonify({'error': 'Thiếu thông tin bắt buộc: hospital_id, blood_type, amount_ml'}), 400

    hospital = User.query.filter_by(id=data['hospital_id']).first()
    if not hospital:
        return jsonify({'error': 'Không tìm thấy bệnh viện'}), 404

    try:
        urgen_val = data.get('urgency', 'Cần gấp')
        d_type = data.get('donation_type', 'Toàn phần')
        new_req = BloodRequest(
            hospital_id=data['hospital_id'],
            blood_type=data['blood_type'],
            amount_ml=int(data['amount_ml']),
            urgency=urgen_val,
            address=data.get('address', hospital.address or ''),
            note=data.get('note', ''),
            expected_date=data.get('expected_date'),
            expiration_date=data.get('expiration_date'),
            time_slot=data.get('time_slot'),
            donation_type=d_type,
            status='open'
        )
        db.session.add(new_req)
        db.session.commit()

        # Phát sóng thông báo đẩy PUSH NOTIFICATION
        def broadcast_scheduled_request(hospital_name, b_type, don_type, req_amount):
            with app.app_context():
                try:
                    eligible_users = User.query.filter(
                        User.role == 'donor',
                        User.blood_type.in_(['Khác', b_type])
                    ).all()
                    push_donor_ids = [u.id for u in eligible_users if u.id]

                    print(f"Bắt đầu phát sóng thông báo Lịch mới cho {len(push_donor_ids)} người")
                    
                    if FCM_ENABLED:
                        for uid in push_donor_ids:
                            tokens = PushToken.query.filter_by(user_id=uid).all()
                            for pt in tokens:
                                try:
                                    msg_fcm = messaging.Message(
                                        notification=messaging.Notification(
                                            title="Lịch hiến máu mới!",
                                            body=f"{hospital_name} đang tiếp nhận {don_type} nhóm {b_type}. Vui lòng mở ứng dụng để đăng ký."
                                        ),
                                        token=pt.token
                                    )
                                    messaging.send(msg_fcm)
                                except Exception: pass
                except Exception as e:
                    print(f"Lỗi gửi thông báo lịch định kỳ: {e}")

        # Chỉ gửi khi không phải "Khẩn cấp" (vì khẩn cấp hệ thống đã có notify_donors gửi bằng AI)
        # Nút "Tạo Yêu Cầu Ghi Nhận" bản chất là "Thường" hoặc "Cần gấp". Nhưng app đang gọi "Cần gấp" là normal ở Home.tsx
        if urgen_val != 'Khẩn cấp':
             threading.Thread(target=broadcast_scheduled_request, args=(hospital.name, new_req.blood_type, d_type, new_req.amount_ml)).start()

        return jsonify({'message': 'Tạo yêu cầu thành công', 'blood_request': new_req.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi create_blood_request: {e}")
        return jsonify({'error': 'Lỗi tạo yêu cầu'}), 500


@app.route('/blood-requests/<int:req_id>/register', methods=['POST'])
def register_blood_donation(req_id):
    """Tình nguyện viên đăng ký hiến máu cho một yêu cầu (không cần chọn giờ nữa)."""
    data = request.get_json()
    donor_id = data.get('donor_id')

    if not donor_id:
        return jsonify({'error': 'Thiếu donor_id'}), 400

    blood_req = BloodRequest.query.get(req_id)
    if not blood_req:
        return jsonify({'error': 'Không tìm thấy yêu cầu hiến máu'}), 404
    if blood_req.status != 'open':
        return jsonify({'error': 'Yêu cầu này đã đóng'}), 400

    donor = User.query.get(donor_id)
    if not donor:
        return jsonify({'error': 'Không tìm thấy người hiến'}), 404
        
    is_eligible, err_msg = check_donation_eligibility(donor_id)
    if not is_eligible:
        return jsonify({'error': err_msg}), 400

    # Kiểm tra đã đăng ký chưa
    existing = DonationRegistration.query.filter_by(
        blood_request_id=req_id, donor_id=donor_id
    ).first()
    if existing:
        return jsonify({'error': 'Bạn đã đăng ký cho yêu cầu này rồi'}), 409

    try:
        reg = DonationRegistration(
            blood_request_id=req_id,
            donor_id=donor_id,
            time_slot=blood_req.time_slot or 'Liên hệ sau',
            status='registered'
        )
        db.session.add(reg)
        # Tặng 10 điểm khi đăng ký
        donor.reward_points = (donor.reward_points or 0) + 10
        db.session.commit()
        return jsonify({
            'message': 'Đăng ký hiến máu thành công! Bạn được tặng 10 điểm.',
            'registration': reg.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi register_blood_donation: {e}")
        return jsonify({'error': 'Lỗi đăng ký'}), 500


@app.route('/blood-requests/<int:req_id>/registrations', methods=['GET'])
def get_registrations(req_id):
    """Bệnh viện xem danh sách tình nguyện viên đã đăng ký cho yêu cầu."""
    blood_req = BloodRequest.query.get(req_id)
    if not blood_req:
        return jsonify({'error': 'Không tìm thấy yêu cầu'}), 404
    regs = DonationRegistration.query.filter_by(blood_request_id=req_id).order_by(DonationRegistration.time_slot).all()
    return jsonify({
        'blood_request': blood_req.to_dict(),
        'count': len(regs),
        'registrations': [r.to_dict() for r in regs]
    }), 200

# --- ADMIN API: DANH SÁCH PENDING & XÁC NHẬN ---
@app.route('/admin/pending_donations', methods=['GET'])
def get_pending_donations():
    # Chỉ lấy những người ĐÃ XÁC NHẬN qua email (status='accepted')
    records = DonationRecord.query.filter_by(status='accepted').all()
    results = []
    for r in records:
        user = db.session.get(User, r.user_id)
        if user:
            results.append({
                'record_id': r.id,
                'user_name': user.name,
                'phone': user.phone,
                'blood_type': user.blood_type,
                'donation_date': r.donation_date.isoformat() if r.donation_date else None
            })
    return jsonify({'count': len(results), 'pending_donations': results}), 200

@app.route('/admin/confirm_donation/<int:record_id>', methods=['POST'])
def confirm_donation(record_id):
    data = request.get_json()
    amount_ml = data.get('amount_ml')
    donation_type = data.get('donation_type') # Lấy loại hiến máu từ Frontend
    donation_date_str = data.get('donation_date') # Lấy ngày hiến từ Frontend

    if amount_ml is None or not isinstance(amount_ml, int) or amount_ml <= 0:
        return jsonify({'error': 'Lượng máu không hợp lệ'}), 400

    record = db.session.get(DonationRecord, record_id)
    if not record:
        return jsonify({'error': 'Không tìm thấy record'}), 404
        
    if record.status == 'completed':
        return jsonify({'error': 'Record này đã được xác nhận từ trước'}), 400

    user = db.session.get(User, record.user_id)
    if not user:
        return jsonify({'error': 'Không tìm thấy User của record này'}), 404

    try:
        # 1. Xử lý ngày hiến máu (Nếu Admin nhập thì lấy, không thì lấy ngày mặc định)
        donation_date = datetime.now().date()
        if donation_date_str:
            try:
                donation_date = parse(donation_date_str).date()
            except Exception:
                pass # Bỏ qua lỗi parse, dùng ngày mặc định
                
        # 2. Cập nhật record
        record.status = 'completed'
        record.amount_ml = amount_ml
        record.donation_date = donation_date # Lưu ngày hiến do Admin chọn
        if donation_type:
             record.donation_type = donation_type # Lưu loại hiến máu
        
        # 3. Cập nhật thông tin User
        user.donations_count += 1
        user.last_donation = donation_date
        user.reward_points += 10 # Tặng điểm khi admin xác nhận hiến máu
        
        db.session.commit()
        
        # 4. Gửi email cảm ơn + link ẩn danh (background thread)
        token = secrets.token_urlsafe(32)
        record.anonymous_token = token
        db.session.commit()
        
        if user.email:
            t = threading.Thread(
                target=send_thank_you_email,
                args=(user.email, user.name, record.id, token),
                daemon=True
            )
            t.start()
        
        return jsonify({
            'message': 'Xác nhận hiến máu thành công',
            'record': record.to_dict(),
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi Admin Confirm: {e}")
        return jsonify({'error': 'Lỗi hệ thống khi xác nhận'}), 500


@app.route('/admin/donor_growth', methods=['GET'])
def get_donor_growth():
    try:
        records = DonationRecord.query.filter_by(status='completed').all()
        month_counts = {}
        for r in records:
            if r.donation_date:
                month_str = r.donation_date.strftime('%Y-%m')
                # Lấy tên loại máu
                dtype = r.donation_type if r.donation_type else 'Toàn phần'
                if 'Toàn phần' in dtype:
                    category = 'Toàn phần'
                elif 'Tiểu cầu' in dtype:
                    category = 'Tiểu cầu'
                elif 'Huyết tương' in dtype:
                    category = 'Huyết tương'
                else:
                    category = 'Khác'
                    
                if month_str not in month_counts:
                    month_counts[month_str] = {'Toàn phần': 0, 'Tiểu cầu': 0, 'Huyết tương': 0, 'Khác': 0}
                month_counts[month_str][category] += 1
        
        sorted_months = sorted(month_counts.keys())
        last_4_months = sorted_months[-4:] if len(sorted_months) >= 4 else sorted_months
        
        chart_data = []
        for m in last_4_months:
            month_num = m.split('-')[1]
            data = {'name': f'T{int(month_num)}'}
            data.update(month_counts[m])
            chart_data.append(data)
            
        # Nếu chưa đủ 4 tháng, điền thêm giá trị rỗng cho đủ layout biểu đồ
        while len(chart_data) < 4:
            chart_data.insert(0, {'name': '-', 'Toàn phần': 0, 'Tiểu cầu': 0, 'Huyết tương': 0, 'Khác': 0})
            
        return jsonify({'chart_data': chart_data}), 200
    except Exception as e:
        print(f"Lỗi get_donor_growth: {e}")
        return jsonify({'error': 'Lỗi server'}), 500

@app.route('/admin/scheduled_registrations', methods=['GET'])
def get_scheduled_registrations():
    try:
        registrations = DonationRegistration.query.join(BloodRequest).filter(
            DonationRegistration.status == 'registered',
            BloodRequest.status == 'open'
        ).all()
        
        results = []
        for reg in registrations:
            user = db.session.get(User, reg.donor_id)
            if user:
                results.append({
                    'reg_id': reg.id,
                    'user_name': user.name,
                    'phone': user.phone,
                    'blood_type': user.blood_type,
                    'time_slot': reg.time_slot,
                    'expected_date': reg.blood_request.expected_date,
                    'amount_ml': reg.blood_request.amount_ml,
                    'urgency': reg.blood_request.urgency
                })
        return jsonify({'count': len(results), 'scheduled_registrations': results}), 200
    except Exception as e:
        print(f"Lỗi scheduled_registrations: {e}")
        return jsonify({'error': 'Lỗi lấy danh sách'}), 500

@app.route('/admin/confirm_scheduled_donation/<int:reg_id>', methods=['POST'])
def confirm_scheduled_donation(reg_id):
    data = request.get_json()
    amount_ml = data.get('amount_ml')
    donation_type = data.get('donation_type')
    donation_date_str = data.get('donation_date')

    if amount_ml is None or not isinstance(amount_ml, int) or amount_ml <= 0:
        return jsonify({'error': 'Lượng máu không hợp lệ'}), 400

    reg = db.session.get(DonationRegistration, reg_id)
    if not reg:
        return jsonify({'error': 'Không tìm thấy đăng ký này'}), 404
        
    if reg.status == 'completed':
        return jsonify({'error': 'Đăng ký này đã được xác nhận'}), 400

    user = db.session.get(User, reg.donor_id)
    if not user:
        return jsonify({'error': 'Không tìm thấy User của đăng ký này'}), 404

    try:
        donation_date = datetime.now().date()
        if donation_date_str:
            try:
                donation_date = parse(donation_date_str).date()
            except Exception:
                pass 
                
        # Cập nhật reg và đóng blood_request tương ứng luôn
        reg.status = 'completed'
        if reg.blood_request:
            reg.blood_request.status = 'completed'
        
        # Tạo mới DonationRecord
        new_record = DonationRecord(
            user_id=user.id,
            donation_date=donation_date,
            amount_ml=amount_ml,
            status='completed',
            donation_type=donation_type
        )
        db.session.add(new_record)
        
        user.donations_count += 1
        user.last_donation = donation_date
        user.reward_points += 10
        
        db.session.commit()
        
        # Gửi email cảm ơn + link ẩn danh (background thread)
        token = secrets.token_urlsafe(32)
        new_record.anonymous_token = token
        db.session.commit()
        
        if user.email:
            t = threading.Thread(
                target=send_thank_you_email,
                args=(user.email, user.name, new_record.id, token),
                daemon=True
            )
            t.start()
        
        return jsonify({
            'message': 'Xác nhận hiến máu thành công',
            'record': new_record.to_dict(),
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi Admin Confirm Scheduled: {e}")
        return jsonify({'error': 'Lỗi hệ thống khi xác nhận'}), 500


@app.route('/admin/cancel_scheduled_registration/<int:reg_id>', methods=['DELETE'])
def admin_cancel_scheduled_registration(reg_id):
    """Admin hủy bỏ đăng ký hiến máu thường xuyên (No-show)."""
    reg = db.session.get(DonationRegistration, reg_id)
    if not reg:
        return jsonify({'error': 'Không tìm thấy đăng ký này'}), 404
        
    try:
        db.session.delete(reg)
        db.session.commit()
        return jsonify({'message': 'Đã xóa đăng ký vì người dùng không đến'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi cancel_scheduled_registration: {e}")
        return jsonify({'error': 'Lỗi hệ thống khi xóa'}), 500


@app.route('/admin/cancel_emergency_donation/<int:record_id>', methods=['DELETE'])
def admin_cancel_emergency_donation(record_id):
    """Admin hủy bỏ đăng ký hiển máu khẩn cấp (No-show - xóa record pending)."""
    record = db.session.get(DonationRecord, record_id)
    if not record:
        return jsonify({'error': 'Không tìm thấy bản ghi này'}), 404
        
    if record.status != 'pending':
        return jsonify({'error': 'Chỉ có thể xóa các bản ghi Khẩn cấp đang chờ'}), 400
        
    try:
        db.session.delete(record)
        db.session.commit()
        return jsonify({'message': 'Đã xóa đăng ký vì lượt khẩn cấp không thành công'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi cancel_emergency_donation: {e}")
        return jsonify({'error': 'Lỗi hệ thống khi xóa'}), 500


@app.route('/admin/donation_stats', methods=['GET'])
def get_donation_stats():
    """Thống kê số lượt hiến máu thực tế (completed), có thể lọc theo nhóm máu và ngày."""
    blood_type_filter = request.args.get('blood_type')  # ví dụ: 'O', 'A', 'B', 'AB'
    date_from_str = request.args.get('date_from')       # ví dụ: '2026-01-01'
    date_to_str = request.args.get('date_to')           # ví dụ: '2026-12-31'

    try:
        query = DonationRecord.query.filter_by(status='completed')

        if date_from_str:
            try:
                date_from = parse(date_from_str).date()
                query = query.filter(DonationRecord.donation_date >= date_from)
            except Exception:
                pass

        if date_to_str:
            try:
                date_to = parse(date_to_str).date()
                query = query.filter(DonationRecord.donation_date <= date_to)
            except Exception:
                pass

        records = query.all()

        # Lọc theo nhóm máu nếu có (qua bảng User)
        if blood_type_filter:
            filtered = [r for r in records if db.session.get(User, r.user_id) and db.session.get(User, r.user_id).blood_type == blood_type_filter]
        else:
            filtered = records

        # Tính tổng ml hiến được
        total_ml = sum(r.amount_ml for r in filtered if r.amount_ml)

        # Thống kê theo nhóm máu
        blood_type_counts = {}
        for r in filtered:
            user = db.session.get(User, r.user_id)
            if user:
                bt = user.blood_type or 'Chưa rõ'
                blood_type_counts[bt] = blood_type_counts.get(bt, 0) + 1

        # Thống kê theo loại hiến
        donation_type_counts = {}
        for r in filtered:
            dt = r.donation_type or 'Toàn phần'
            donation_type_counts[dt] = donation_type_counts.get(dt, 0) + 1

        return jsonify({
            'total_donations': len(filtered),
            'total_ml': total_ml,
            'by_blood_type': blood_type_counts,
            'by_donation_type': donation_type_counts
        }), 200

    except Exception as e:
        print(f"Lỗi stats: {e}")
        return jsonify({'error': 'Lỗi hệ thống'}), 500

@app.route('/admin/donors_list', methods=['GET'])
def admin_donors_list():
    try:
        users = User.query.filter_by(role='donor').all()
        donors_data = []
        for d in users:
            records = DonationRecord.query.filter_by(user_id=d.id, status='completed').all()
            total_ml = sum(r.amount_ml or 0 for r in records)
            
            records.sort(key=lambda r: r.donation_date, reverse=True)
            last_date_str = records[0].donation_date.isoformat() if records else (d.last_donation.isoformat() if d.last_donation else None)
            
            is_eligible, reason, days_left = True, "Đủ điều kiện hiến", 0
            if last_date_str:
                last_d = datetime.strptime(last_date_str, '%Y-%m-%d').date()
                days_passed = (datetime.now().date() - last_d).days
                last_type = records[0].donation_type if records else 'Toàn phần'
                # Thời gian phục hồi theo chu kỳ
                required_days = 14 if last_type in ['Tiểu cầu', 'Huyết tương'] else 84
                
                if days_passed < required_days:
                    is_eligible = False
                    days_left = required_days - days_passed
                    reason = f"Đang chờ hồi phục (còn {days_left} ngày)"

            donors_data.append({
                'id': d.id,
                'name': d.name,
                'phone': d.phone,
                'email': d.email,
                'blood_type': d.blood_type or 'Chưa rõ',
                'donations_count': len(records),
                'total_ml': total_ml,
                'last_donated': last_date_str,
                'is_anonymous': records[0].is_anonymous if records else False,  # Lấy từ lần hiến gần nhất
                'status': {
                    'eligible': is_eligible,
                    'reason': reason,
                    'days_left': days_left
                }
            })
        
        # Sort by last_donated (null goes to bottom)
        donors_data.sort(key=lambda x: x['last_donated'] or '1970-01-01', reverse=True)
            
        return jsonify({'donors': donors_data}), 200
    except Exception as e:
        print(f"Lỗi donors_list: {e}")
        return jsonify({'error': 'Lỗi server'}), 500

# --- CHẠY APP ---
if __name__ == '__main__':
    with app.app_context():
        # Tạo bảng nếu chưa tồn tại
        db.create_all()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)