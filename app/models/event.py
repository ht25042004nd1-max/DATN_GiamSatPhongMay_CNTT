# ============================================================
# app/models/event.py — Model bảng events (cảnh báo)
# ============================================================
from datetime import datetime
from app import db


class Event(db.Model):
    __tablename__ = 'events'

    id           = db.Column(db.Integer,  primary_key=True)
    room_id      = db.Column(db.Integer,  db.ForeignKey('rooms.id'), nullable=True)
    camera_id    = db.Column(db.Integer,  db.ForeignKey('cameras.id'), nullable=True)
    computer_id  = db.Column(db.Integer,  db.ForeignKey('computers.id'), nullable=True)
    roi_id       = db.Column(db.Integer,  db.ForeignKey('rois.id'), nullable=True)
    roi_name     = db.Column(db.String(80))        # Snapshot tên ROI
    pose         = db.Column(db.String(40))        # Tư thế khi xảy ra
    level        = db.Column(db.String(20))        # 'low' | 'medium' | 'high'
    person_count = db.Column(db.Integer, default=1)
    started_at   = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at     = db.Column(db.DateTime, nullable=True)
    status       = db.Column(db.String(20), default='pending')
                               # 'pending' | 'confirmed' | 'ignored'
    note         = db.Column(db.Text, nullable=True)

    # --- V3 Additions ---
    confidence_score = db.Column(db.Float, nullable=True) # % tin cậy của AI
    handled_by       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    handled_at       = db.Column(db.DateTime, nullable=True)

    # Quan hệ với người xử lý
    handler = db.relationship('User', foreign_keys=[handled_by], backref='handled_events', lazy=True)

    @property
    def duration_seconds(self):
        end = self.ended_at or datetime.utcnow()
        return int((end - self.started_at).total_seconds())

    @property
    def status_label(self):
        return {'pending': 'Chờ xử lý', 'confirmed': 'Đã xác nhận', 'ignored': 'Đã bỏ qua'}.get(self.status, self.status)

    @property
    def level_label(self):
        return {'low': 'Thấp', 'medium': 'Trung bình', 'high': 'Cao'}.get(self.level, self.level)

    @property
    def pose_label(self):
        return {
            'Quy':        'Quỳ',
            'Ngoi':       'Ngồi',
            'Cui nguoi':  'Cúi người',
            'Dung':       'Đứng',
        }.get(self.pose, self.pose)

    def to_dict(self):
        return {
            'id':           self.id,
            'room_id':      self.room_id,
            'camera_id':    self.camera_id,
            'computer_id':  self.computer_id,
            'roi_id':       self.roi_id,
            'roi_name':     self.roi_name or 'N/A',
            'pose':         self.pose,
            'pose_label':   self.pose_label,
            'level':        self.level,
            'level_label':  self.level_label,
            'person_count': self.person_count,
            'started_at':   self.started_at.strftime('%d/%m/%Y %H:%M:%S') if self.started_at else None,
            'ended_at':     self.ended_at.strftime('%d/%m/%Y %H:%M:%S') if self.ended_at else None,
            'duration':     self.duration_seconds,
            'status':       self.status,
            'status_label': self.status_label,
            'note':         self.note,
            'confidence_score': self.confidence_score,
            'handled_by':   self.handled_by,
            'handled_at':   self.handled_at.strftime('%d/%m/%Y %H:%M:%S') if self.handled_at else None,
            'handler_name': self.handler.display_name if self.handler else None
        }

    def __repr__(self):
        return f'<Event {self.id}: {self.pose} in {self.roi_name}>'
