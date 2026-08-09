# ============================================================
# app/models/__init__.py — Export tất cả model
# Import ở đây để SQLAlchemy tự nhận diện và tạo bảng đầy đủ
# ============================================================

from app.models.user import User
from app.models.login_log import LoginLog
from app.models.room import Room
from app.models.camera import Camera
from app.models.computer import Computer
from app.models.iot_device import IoTDevice
from app.models.roi import ROI
from app.models.event import Event
from app.models.setting import SystemSetting
from app.models.audit_log import AuditLog

__all__ = [
    'User', 'LoginLog', 'Room', 'Camera', 'Computer', 'IoTDevice', 
    'ROI', 'Event', 'SystemSetting', 'AuditLog'
]
