# ============================================================
# app/models/setting.py — Model lưu cài đặt hệ thống trong database
#
# Thiết kế key-value: linh hoạt, dễ mở rộng
# Ưu tiên: DB > .env > giá trị mặc định hardcode
# ============================================================
from datetime import datetime
from app import db


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'

    id         = db.Column(db.Integer,   primary_key=True)
    key        = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value      = db.Column(db.Text,      nullable=True)
    updated_at = db.Column(db.DateTime,  default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Helper class methods ───────────────────────────────
    @classmethod
    def get(cls, key: str, default=None):
        """Lấy giá trị theo key. Trả về default nếu không tồn tại."""
        row = cls.query.filter_by(key=key).first()
        if row is None or row.value is None:
            return default
        return row.value

    @classmethod
    def set(cls, key: str, value):
        """Upsert: tạo mới hoặc cập nhật giá trị theo key."""
        row = cls.query.filter_by(key=key).first()
        if row is None:
            row = cls(key=key, value=str(value) if value is not None else None)
            db.session.add(row)
        else:
            row.value = str(value) if value is not None else None
            row.updated_at = datetime.utcnow()
        db.session.commit()

    @classmethod
    def get_bool(cls, key: str, default=False) -> bool:
        val = cls.get(key)
        if val is None:
            return default
        return val.lower() in ('1', 'true', 'yes', 'on')

    @classmethod
    def get_int(cls, key: str, default=0) -> int:
        val = cls.get(key)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    @classmethod
    def all_as_dict(cls) -> dict:
        """Trả về tất cả settings dạng dict {key: value}."""
        return {row.key: row.value for row in cls.query.all()}

    def __repr__(self):
        return f'<Setting {self.key}={self.value!r}>'
