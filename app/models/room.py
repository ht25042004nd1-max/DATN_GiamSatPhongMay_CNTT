from app import db

class Room(db.Model):
    """
    Model quản lý thông tin các phòng máy tính đang được giám sát.
    """
    __tablename__ = 'rooms'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False) # Tên phòng máy
    location = db.Column(db.String(200), nullable=True) # Vị trí
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Quan hệ 1-nhiều
    cameras = db.relationship('Camera', backref='room', lazy=True, cascade='all, delete-orphan')
    computers = db.relationship('Computer', backref='room', lazy=True, cascade='all, delete-orphan')
    iot_devices = db.relationship('IoTDevice', backref='room', lazy=True, cascade='all, delete-orphan')
    events = db.relationship('Event', backref='room', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def camera_count(self):
        return len(self.cameras)

    @property
    def computer_count(self):
        return len(self.computers)

    @property
    def iot_device_count(self):
        return len(self.iot_devices)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'is_active': self.is_active,
            'camera_count': self.camera_count,
            'computer_count': self.computer_count,
            'iot_device_count': self.iot_device_count
        }

    def __repr__(self):
        return f'<Room {self.name}>'
