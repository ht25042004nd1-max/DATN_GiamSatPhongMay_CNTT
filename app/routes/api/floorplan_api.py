# ============================================================
# app/routes/floorplan_routes.py — API cho Bản Đồ Phòng Máy
# ============================================================
import json
import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required, current_user

from app.utils.decorators import admin_required

floorplan_bp = Blueprint('floorplan', __name__)

# Đường dẫn đến file cấu hình layout
_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'floorplan_config.json')
)


def _load_config():
    """Đọc file cấu hình layout phòng máy."""
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(data):
    """Lưu cấu hình layout vào file JSON."""
    with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Trang Bản Đồ Phòng Máy ──────────────────────────────────
@floorplan_bp.route('/floorplan')
@login_required
def floorplan():
    """Trang Bản Đồ Phòng Máy Trực Quan."""
    from app.models.room import Room
    rooms = Room.query.all()
    return render_template('floorplan.html', rooms=rooms, active_page='floorplan')


@floorplan_bp.route('/api/floorplan/devices', methods=['GET'])
@login_required
def get_devices():
    from app.models.camera import Camera
    from app.models.computer import Computer
    from app.models.iot_device import IoTDevice

    room_id = request.args.get('room_id')
    if not room_id:
        return jsonify({'cameras': [], 'computers': [], 'iot_devices': []})

    cameras = Camera.query.filter_by(room_id=room_id).all()
    computers = Computer.query.filter_by(room_id=room_id).all()
    iot_devices = IoTDevice.query.filter_by(room_id=room_id).all()

    return jsonify({
        'cameras': [{'id': c.id, 'name': c.name, 'x_pos': c.x_pos, 'y_pos': c.y_pos, 'status': getattr(c, 'is_active', True)} for c in cameras],
        'computers': [c.to_dict() for c in computers],
        'iot_devices': [{'id': c.id, 'name': c.name, 'x_pos': c.x_pos, 'y_pos': c.y_pos, 'status': getattr(c, 'status', 'unknown')} for c in iot_devices]
    })


@floorplan_bp.route('/api/floorplan/devices', methods=['POST'])
@login_required
def save_device_positions():
    from app import db
    from app.models.camera import Camera
    from app.models.computer import Computer
    from app.models.iot_device import IoTDevice

    data = request.get_json()
    positions = data.get('positions', [])

    for p in positions:
        type_ = p.get('type')
        id_ = p.get('id')
        x_pos = p.get('x_pos', 0)
        y_pos = p.get('y_pos', 0)

        if type_ == 'camera':
            item = Camera.query.get(id_)
        elif type_ == 'computer':
            item = Computer.query.get(id_)
        elif type_ == 'iot':
            item = IoTDevice.query.get(id_)
        else:
            continue
            
        if item:
            item.x_pos = x_pos
            item.y_pos = y_pos

    db.session.commit()
    return jsonify({'success': True})


# ── API: Trạng thái realtime ────────────────────────────────
@floorplan_bp.route('/api/floorplan/status', methods=['GET'])
@login_required
def get_status():
    """
    Trả về trạng thái realtime cho bản đồ:
    - Danh sách zone đang có alert pending (để highlight đỏ)
    - Trạng thái IoT hiện tại
    - Số cảnh báo pending tổng cộng
    """
    from app.models.event import Event
    from app.services.esp32_service import get_iot_status

    cfg = _load_config()
    roi_zone_map = cfg.get('roi_zone_map', {})

    # Lấy các event đang pending trong 30 phút gần đây
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    pending_events = (
        Event.query
        .filter(Event.status == 'pending')
        .filter(Event.started_at >= cutoff)
        .order_by(Event.started_at.desc())
        .limit(50)
        .all()
    )

    # Map các event sang zone bị ảnh hưởng
    alert_zones = set()
    zone_alerts = {}  # zone_id -> [event dicts]

    for ev in pending_events:
        roi_name = ev.roi_name or ''
        # Tìm zone nào match với ROI name
        matched_zones = roi_zone_map.get(roi_name, [])
        if not matched_zones:
            # Fallback: nếu không match chính xác → tìm gần đúng
            for roi_key, zones in roi_zone_map.items():
                if roi_key.lower() in roi_name.lower() or roi_name.lower() in roi_key.lower():
                    matched_zones = zones
                    break
            if not matched_zones:
                # Nếu vẫn không tìm thấy → highlight tất cả
                matched_zones = list(set(z for zones in roi_zone_map.values() for z in zones))

        for zone in matched_zones:
            alert_zones.add(zone)
            if zone not in zone_alerts:
                zone_alerts[zone] = []
            zone_alerts[zone].append({
                'id': ev.id,
                'roi_name': ev.roi_name,
                'pose': ev.pose,
                'level': ev.level,
                'started_at': ev.started_at.strftime('%H:%M:%S') if ev.started_at else '',
                'duration_seconds': ev.duration_seconds,
                'person_count': ev.person_count,
            })

    # Trạng thái IoT
    try:
        iot = get_iot_status()
    except Exception:
        iot = {'is_online': False, 'devices': {'led': 0, 'buzzer': 0, 'relay': 0}}

    # Trạng thái camera (lấy camera đầu tiên)
    try:
        from app.routes.web.main_views import _get_camera
        from app.models.camera import Camera
        first_cam = Camera.query.filter_by(is_active=True).first()
        if first_cam:
            cam = _get_camera(first_cam.id)
            cam_status = cam.get_status()
            cam_online = cam_status.get('is_online', False)
            cam_fps = cam_status.get('fps', 0)
        else:
            cam_online = False
            cam_fps = 0
    except Exception:
        cam_online = False
        cam_fps = 0

    return jsonify({
        'alert_zones': list(alert_zones),          # ['A', 'C', ...] – zones đang có alert
        'zone_alerts': zone_alerts,                 # chi tiết alerts theo zone
        'pending_total': len(pending_events),
        'iot': iot,
        'camera': {
            'is_online': cam_online,
            'fps': cam_fps
        },
        'timestamp': datetime.now().strftime('%H:%M:%S')
    })
