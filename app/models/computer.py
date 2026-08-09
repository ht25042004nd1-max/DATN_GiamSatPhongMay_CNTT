# ============================================================
# app/models/computer.py — Model bảng computers
# ============================================================
from datetime import datetime
from app import db

class Computer(db.Model):
    __tablename__ = 'computers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) # VD: Máy 01, Máy 02
    mac_address = db.Column(db.String(50), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), default='offline') # online, offline, maintenance
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    x_pos = db.Column(db.Integer, default=0)
    y_pos = db.Column(db.Integer, default=0)
    last_seen = db.Column(db.DateTime, nullable=True)         # Lần ping thành công gần nhất
    last_ping_ms = db.Column(db.Integer, nullable=True)       # Thời gian phản hồi (ms)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        # Tính trạng thái mạng gần đây
        last_seen_str = None
        if self.last_seen:
            delta = (datetime.utcnow() - self.last_seen).total_seconds()
            if delta < 60:
                last_seen_str = f"{int(delta)}s trước"
            elif delta < 3600:
                last_seen_str = f"{int(delta//60)}m trước"
            else:
                last_seen_str = self.last_seen.strftime('%d/%m %H:%M')

        return {
            'id': self.id,
            'name': self.name,
            'mac_address': self.mac_address,
            'ip_address': self.ip_address,
            'status': self.status,
            'room_id': self.room_id,
            'room_name': self.room.name if self.room else None,
            'x_pos': self.x_pos,
            'y_pos': self.y_pos,
            'last_seen': last_seen_str,
            'last_ping_ms': self.last_ping_ms,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None
        }

    def __repr__(self):
        return f'<Computer {self.id}: {self.name}>'
