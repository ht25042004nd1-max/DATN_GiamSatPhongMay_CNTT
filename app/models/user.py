# ============================================================
# app/models/user.py — Model tài khoản người dùng
# ============================================================
from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class User(UserMixin, db.Model):
    """
    Bảng lưu thông tin tài khoản đăng nhập.
    - Kế thừa UserMixin để tích hợp Flask-Login (cung cấp sẵn is_authenticated, is_active...)
    - Mật khẩu được lưu dạng HASH (không lưu plain text) bằng werkzeug.security
    """
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)

    # Tên đăng nhập, duy nhất trong hệ thống
    username      = db.Column(db.String(50), unique=True, nullable=False)

    # Mật khẩu đã băm — xem hàm set_password() bên dưới để hiểu cách hoạt động
    password_hash = db.Column(db.String(255), nullable=False)

    # Vai trò: 'admin' (toàn quyền), 'monitor' (giám sát viên - được thao tác thiết bị), 'viewer' (chỉ xem báo cáo)
    role          = db.Column(db.String(20), default='viewer', nullable=False)

    # Thông tin bổ sung
    display_name  = db.Column(db.String(100), nullable=True)
    email         = db.Column(db.String(120), unique=True, nullable=True)
    phone         = db.Column(db.String(20), nullable=True)

    # --- Cơ chế khóa tài khoản khi đăng nhập sai nhiều lần ---
    # Đếm số lần nhập sai liên tiếp, reset về 0 khi đăng nhập thành công
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)

    # Thời điểm tài khoản bị khóa (None = không bị khóa)
    locked_until  = db.Column(db.DateTime, nullable=True)

    # Thời gian tạo tài khoản
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship: 1 user có nhiều bản ghi đăng nhập
    login_logs    = db.relationship('LoginLog', backref='user', lazy=True,
                                    cascade='all, delete-orphan')

    # ─── Phương thức xử lý mật khẩu ────────────────────────
    def set_password(self, password):
        """
        Băm mật khẩu và lưu vào cột password_hash.
        
        Cách hoạt động (để trả lời hội đồng):
        - Dùng thuật toán scrypt (mặc định của werkzeug).
        - Hàm băm là một chiều: chỉ có thể kiểm tra, không thể giải mã ngược.
        - Mỗi lần băm, werkzeug tự tạo thêm "salt" ngẫu nhiên nên cùng mật khẩu
          nhưng 2 lần băm sẽ cho kết quả khác nhau — an toàn hơn so với MD5/SHA1.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """
        Kiểm tra mật khẩu nhập vào có khớp với hash đang lưu không.
        Trả về True nếu đúng, False nếu sai.
        """
        return check_password_hash(self.password_hash, password)

    def is_locked(self):
        """Kiểm tra tài khoản có đang bị khóa tạm thời không."""
        if self.locked_until and datetime.utcnow() < self.locked_until:
            return True
        return False

    def __repr__(self):
        return f"<User {self.username} [{self.role}]>"
