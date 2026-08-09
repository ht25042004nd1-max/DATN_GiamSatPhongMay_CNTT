# ============================================================
# app/routes/api/room_api.py — RESTful API cho Room
# ============================================================
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app import db
from app.models.room import Room
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

room_bp = Blueprint('room', __name__)

@room_bp.route('/rooms')
@login_required
def index():
    rooms = Room.query.order_by(Room.id.desc()).all()
    return render_template('rooms/index.html', rooms=rooms, active_page='rooms')

@room_bp.route('/api/rooms', methods=['GET'])
@login_required
def get_rooms():
    rooms = Room.query.order_by(Room.id.desc()).all()
    return jsonify([r.to_dict() for r in rooms])

@room_bp.route('/api/rooms', methods=['POST'])
@login_required
@admin_required
def create_room():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Thiếu thông tin tên phòng'}), 400
    
    if Room.query.filter_by(name=data['name']).first():
        return jsonify({'error': 'Tên phòng đã tồn tại'}), 400

    room = Room(
        name=data['name'],
        location=data.get('location'),
        is_active=data.get('is_active', True)
    )
    db.session.add(room)
    db.session.commit()
    log_audit('CREATE_ROOM', 'Room', room.id, {'name': room.name})
    return jsonify(room.to_dict()), 201

@room_bp.route('/api/rooms/<int:room_id>', methods=['PUT'])
@login_required
@admin_required
def update_room(room_id):
    room = Room.query.get_or_404(room_id)
    data = request.get_json()
    
    if 'name' in data and data['name'] != room.name:
        if Room.query.filter_by(name=data['name']).first():
            return jsonify({'error': 'Tên phòng đã tồn tại'}), 400
        room.name = data['name']
        
    if 'location' in data:
        room.location = data['location']
    if 'is_active' in data:
        room.is_active = bool(data['is_active'])
        
    db.session.commit()
    log_audit('UPDATE_ROOM', 'Room', room.id, {'name': room.name})
    return jsonify(room.to_dict())

@room_bp.route('/api/rooms/<int:room_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_room(room_id):
    room = Room.query.get_or_404(room_id)
    name = room.name
    db.session.delete(room)
    db.session.commit()
    log_audit('DELETE_ROOM', 'Room', room_id, {'name': name})
    return jsonify({'message': 'Đã xóa phòng máy thành công'})
