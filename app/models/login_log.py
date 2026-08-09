# ============================================================
# app/models/login_log.py — Model nhật ký đăng nhập
# ============================================================
from app import db
from datetime import datetime


class LoginLog(db.Model):
    """
    Bảng ghi lại mọi lần đăng nhập vào hệ thống (thành công hoặc thất bại).
    Dùng để kiểm tra lịch sử truy cập khi cần điều tra sự cố.
    """
    __tablename__ = 'login_logs'

    id         = db.Column(db.Integer, primary_key=True)

    # Liên kết với user (nullable=True để vẫn ghi log khi nhập sai username hoàn toàn)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Username nhập vào (ghi lại để theo dõi cả trường hợp sai username)
    username_input = db.Column(db.String(50), nullable=True)

    # Thời điểm đăng nhập
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Địa chỉ IP của máy thực hiện đăng nhập
    ip_address = db.Column(db.String(45), nullable=True)  # 45 ký tự hỗ trợ cả IPv6

    # Trình duyệt / thiết bị (User-Agent HTTP header)
    user_agent = db.Column(db.String(300), nullable=True)

    # Kết quả: 'success' (thành công) hoặc 'failed' (thất bại)
    status     = db.Column(db.String(10), nullable=False)

    # Ghi chú thủ công (VD: "Tài khoản bị khóa", "Sai mật khẩu lần 3"...)
    note       = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<LoginLog user_id={self.user_id} status={self.status} at {self.timestamp}>"
