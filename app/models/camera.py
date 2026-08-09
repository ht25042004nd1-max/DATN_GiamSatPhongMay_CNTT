# ============================================================
# app/models/camera.py — Model bảng cameras
# ============================================================
from datetime import datetime
from app import db

class Camera(db.Model):
    __tablename__ = 'cameras'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rtsp_url = db.Column(db.String(255), nullable=True) # URL stream RTSP hoặc HTTP
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    x_pos = db.Column(db.Integer, default=0)
    y_pos = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Quan hệ 1-nhiều với ROI và Event
    rois = db.relationship('ROI', backref='camera', lazy='dynamic', cascade='all, delete-orphan')
    events = db.relationship('Event', backref='camera', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'rtsp_url': self.rtsp_url,
            'room_id': self.room_id,
            'room_name': self.room.name if self.room else None,
            'is_active': self.is_active,
            'x_pos': self.x_pos,
            'y_pos': self.y_pos,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None
        }

    def __repr__(self):
        return f'<Camera {self.id}: {self.name}>'
