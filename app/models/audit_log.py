# ============================================================
# app/models/audit_log.py — Model bảng audit_logs
# Lịch sử thao tác của người dùng trong hệ thống V3
# ============================================================
from datetime import datetime
from app import db

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action      = db.Column(db.String(100), nullable=False)   # Ví dụ: 'CONFIRM_EVENT', 'UPDATE_SETTINGS'
    target_type = db.Column(db.String(50), nullable=True)     # Ví dụ: 'Event', 'Setting'
    target_id   = db.Column(db.Integer, nullable=True)        # ID của đối tượng bị tác động
    details     = db.Column(db.Text, nullable=True)           # JSON string hoặc text ghi chú chi tiết
    ip_address  = db.Column(db.String(50), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    # Quan hệ ngược (nếu cần thiết) với User
    user = db.relationship('User', backref=db.backref('audit_logs', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<AuditLog {self.action} by User {self.user_id} at {self.created_at}>"
