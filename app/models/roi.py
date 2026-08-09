# ============================================================
# app/models/roi.py — Model bảng rois
# ============================================================
import json
from datetime import datetime
from app import db


class ROI(db.Model):
    __tablename__ = 'rois'

    id         = db.Column(db.Integer,  primary_key=True)
    name       = db.Column(db.String(80), nullable=False)       # Tên ROI
    # Tọa độ polygon lưu dạng JSON: [[x1,y1],[x2,y2],...]
    # Tọa độ chuẩn hóa 0.0–1.0 so với kích thước frame để không phụ thuộc độ phân giải
    points_json = db.Column(db.Text, nullable=False, default='[]')
    level      = db.Column(db.String(20), nullable=False, default='medium')
                           # 'low' | 'medium' | 'high'
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    # Ngưỡng thời gian (giây) để kích hoạt cảnh báo (3–30s, mặc định 5s)
    duration_threshold = db.Column(db.Integer, nullable=False, default=5)
    
    # Ràng buộc camera_id
    camera_id = db.Column(db.Integer, db.ForeignKey('cameras.id'), nullable=True) # Nullable cho migration, có thể đổi thành False sau
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Quan hệ 1-nhiều với events
    events = db.relationship('Event', backref='roi', lazy='dynamic',
                             foreign_keys='Event.roi_id')

    # ── Property helpers ──
    @property
    def points(self):
        """Trả về danh sách điểm [[x,y], ...] từ JSON."""
        try:
            return json.loads(self.points_json)
        except Exception:
            return []

    @points.setter
    def points(self, value):
        """Lưu danh sách điểm thành JSON."""
        self.points_json = json.dumps(value)

    @property
    def level_label(self):
        return {'low': 'Thấp', 'medium': 'Trung bình', 'high': 'Cao'}.get(self.level, self.level)

    @property
    def level_color(self):
        return {'low': '#ffc107', 'medium': '#ff7043', 'high': '#ff3d57'}.get(self.level, '#94a3b8')

    def to_dict(self):
        return {
            'id':                 self.id,
            'name':               self.name,
            'points':             self.points,
            'level':              self.level,
            'level_label':        self.level_label,
            'level_color':        self.level_color,
            'is_active':          self.is_active,
            'duration_threshold': self.duration_threshold,
            'created_at':         self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
        }

    def __repr__(self):
        return f'<ROI {self.id}: {self.name}>'
