# ============================================================
# app/routes/api/iot_device_api.py — RESTful API cho IoTDevice
# ============================================================
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app import db
from app.models.iot_device import IoTDevice
from app.models.room import Room
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

iot_device_bp = Blueprint('iot_device', __name__)

@iot_device_bp.route('/iot_devices')
@login_required
def index():
    devices = IoTDevice.query.order_by(IoTDevice.id.desc()).all()
    rooms = Room.query.all()
    return render_template('iot_devices/index.html', devices=devices, rooms=rooms, active_page='iot_devices')

@iot_device_bp.route('/api/iot_devices', methods=['GET'])
@login_required
def get_iot_devices():
    room_id = request.args.get('room_id')
    query = IoTDevice.query
    if room_id:
        query = query.filter_by(room_id=room_id)
    devices = query.order_by(IoTDevice.id.desc()).all()
    return jsonify([d.to_dict() for d in devices])

@iot_device_bp.route('/api/iot_devices', methods=['POST'])
@login_required
@admin_required
def create_iot_device():
    data = request.get_json()
    if not data or not data.get('name') or not data.get('room_id') or not data.get('device_type'):
        return jsonify({'error': 'Thiếu thông tin bắt buộc'}), 400

    device = IoTDevice(
        name=data['name'],
        device_type=data['device_type'],
        ip_address=data.get('ip_address'),
        status=data.get('status', 'offline'),
        room_id=data['room_id'],
        board_type=data.get('board_type', 'ESP32'),
        protocol=data.get('protocol', 'HTTP'),
        mqtt_topic=data.get('mqtt_topic', 'lab/iot/alert')
    )
    db.session.add(device)
    db.session.commit()
    log_audit('CREATE_IOT_DEVICE', 'IoTDevice', device.id, {'name': device.name, 'board_type': device.board_type})
    return jsonify(device.to_dict()), 201

@iot_device_bp.route('/api/iot_devices/<int:device_id>', methods=['PUT'])
@login_required
@admin_required
def update_iot_device(device_id):
    device = IoTDevice.query.get_or_404(device_id)
    data = request.get_json()
    
    if 'name' in data: device.name = data['name']
    if 'device_type' in data: device.device_type = data['device_type']
    if 'ip_address' in data: device.ip_address = data['ip_address']
    if 'status' in data: device.status = data['status']
    if 'room_id' in data: device.room_id = data['room_id']
    if 'board_type' in data: device.board_type = data['board_type']
    if 'protocol' in data: device.protocol = data['protocol']
    if 'mqtt_topic' in data: device.mqtt_topic = data['mqtt_topic']
        
    db.session.commit()
    log_audit('UPDATE_IOT_DEVICE', 'IoTDevice', device.id, {'name': device.name})
    return jsonify(device.to_dict())

@iot_device_bp.route('/api/iot_devices/<int:device_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_iot_device(device_id):
    device = IoTDevice.query.get_or_404(device_id)
    name = device.name
    db.session.delete(device)
    db.session.commit()
    log_audit('DELETE_IOT_DEVICE', 'IoTDevice', device_id, {'name': name})
    return jsonify({'message': 'Đã xóa thiết bị IoT thành công'})
