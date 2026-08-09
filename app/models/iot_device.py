# ============================================================
# app/models/iot_device.py — Model bảng iot_devices
# ============================================================
from datetime import datetime
from app import db

class IoTDevice(db.Model):
    __tablename__ = 'iot_devices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(50), nullable=False) # esp32, sensor, relay...
    ip_address = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), default='offline') # online, offline, error
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    x_pos = db.Column(db.Integer, default=0)
    y_pos = db.Column(db.Integer, default=0)
    board_type = db.Column(db.String(50), default='ESP32') # ESP32, TCL-508L, HY-LandTiger V2.0
    protocol = db.Column(db.String(50), default='HTTP')   # HTTP, MQTT, TCP_Socket
    mqtt_topic = db.Column(db.String(100), default='lab/iot/alert')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'device_type': self.device_type,
            'ip_address': self.ip_address,
            'status': self.status,
            'room_id': self.room_id,
            'room_name': self.room.name if self.room else None,
            'x_pos': self.x_pos,
            'y_pos': self.y_pos,
            'board_type': self.board_type or 'ESP32',
            'protocol': self.protocol or 'HTTP',
            'mqtt_topic': self.mqtt_topic or 'lab/iot/alert',
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None
        }

    def __repr__(self):
        return f'<IoTDevice {self.id}: {self.name}>'
