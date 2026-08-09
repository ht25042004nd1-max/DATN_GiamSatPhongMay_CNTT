# ============================================================
# app/routes/api/computer_api.py — RESTful API cho Computer
# ============================================================
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app import db
from app.models.computer import Computer
from app.models.room import Room
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

computer_bp = Blueprint('computer', __name__)

@computer_bp.route('/computers')
@login_required
def index():
    computers = Computer.query.order_by(Computer.id.desc()).all()
    rooms = Room.query.all()
    return render_template('computers/index.html', computers=computers, rooms=rooms, active_page='computers')

@computer_bp.route('/api/computers', methods=['GET'])
@login_required
def get_computers():
    room_id = request.args.get('room_id')
    query = Computer.query
    if room_id:
        query = query.filter_by(room_id=room_id)
    computers = query.order_by(Computer.id.desc()).all()
    return jsonify([c.to_dict() for c in computers])

@computer_bp.route('/api/computers', methods=['POST'])
@login_required
@admin_required
def create_computer():
    data = request.get_json()
    if not data or not data.get('name') or not data.get('room_id'):
        return jsonify({'error': 'Thiếu tên hoặc phòng máy'}), 400

    computer = Computer(
        name=data['name'],
        mac_address=data.get('mac_address'),
        ip_address=data.get('ip_address'),
        status=data.get('status', 'offline'),
        room_id=data['room_id']
    )
    db.session.add(computer)
    db.session.commit()
    log_audit('CREATE_COMPUTER', 'Computer', computer.id, {'name': computer.name})
    return jsonify(computer.to_dict()), 201

@computer_bp.route('/api/computers/<int:computer_id>', methods=['PUT'])
@login_required
@admin_required
def update_computer(computer_id):
    computer = Computer.query.get_or_404(computer_id)
    data = request.get_json()
    
    if 'name' in data: computer.name = data['name']
    if 'mac_address' in data: computer.mac_address = data['mac_address']
    if 'ip_address' in data: computer.ip_address = data['ip_address']
    if 'status' in data: computer.status = data['status']
    if 'room_id' in data: computer.room_id = data['room_id']
        
    db.session.commit()
    log_audit('UPDATE_COMPUTER', 'Computer', computer.id, {'name': computer.name})
    return jsonify(computer.to_dict())

@computer_bp.route('/api/computers/<int:computer_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_computer(computer_id):
    computer = Computer.query.get_or_404(computer_id)
    name = computer.name
    db.session.delete(computer)
    db.session.commit()
    log_audit('DELETE_COMPUTER', 'Computer', computer_id, {'name': name})
    return jsonify({'message': 'Đã xóa máy tính thành công'})


@computer_bp.route('/api/computers/ping-status', methods=['GET'])
@login_required
def get_ping_status():
    """Trả về trạng thái Ping hiện tại của tất cả máy tính (dùng cho realtime update)."""
    room_id = request.args.get('room_id')
    query = Computer.query
    if room_id:
        query = query.filter_by(room_id=room_id)
    computers = query.all()
    return jsonify([c.to_dict() for c in computers])


@computer_bp.route('/api/computers/<int:computer_id>/ping-now', methods=['POST'])
@login_required
@admin_required
def ping_computer_now(computer_id):
    """Ping ngay lập tức một máy tính cụ thể theo yêu cầu."""
    try:
        from app.services.ping_service import ping_service
        result = ping_service.ping_single(computer_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

