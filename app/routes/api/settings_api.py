# ============================================================
# app/routes/settings_routes.py — Routes cho trang Cấu hình
# ============================================================
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

settings_bp = Blueprint('settings_api', __name__, url_prefix='/api/settings')


# ── Lấy tất cả settings hiện tại ──────────────────────────
@settings_bp.route('', methods=['GET'])
@login_required
@admin_required
def get_settings():
    """Lấy toàn bộ settings hiện tại (không trả về token thật)."""
    from app.models.setting import SystemSetting
    import os

    token   = SystemSetting.get('telegram_token') or os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = SystemSetting.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID', '')

    return jsonify({
        # Token: chỉ trả về dạng masked để tránh lộ
        'telegram_token':    ('*' * (len(token) - 6) + token[-6:]) if len(token) > 6 else ('*' * len(token)),
        'telegram_chat_id':  chat_id,
        'telegram_enabled':  SystemSetting.get_bool('telegram_enabled', False),
        'telegram_hour_from': SystemSetting.get_int('telegram_hour_from', 0),
        'telegram_hour_to':   SystemSetting.get_int('telegram_hour_to',   23),
        'telegram_send_mode': SystemSetting.get('telegram_send_mode', 'mandatory'),
        'has_token':         bool(token),
        
        # Cấu hình IoT
        'iot_enabled':         SystemSetting.get_bool('iot_enabled', False),
        'iot_esp32_ip':        SystemSetting.get('iot_esp32_ip') or 'http://127.0.0.1:5000/mock_esp32',
        'iot_alert_devices':   SystemSetting.get('iot_alert_devices') or 'led,buzzer,relay',
        'iot_buzzer_duration': SystemSetting.get_int('iot_buzzer_duration', 10),
    })


# ── Lưu settings ──────────────────────────────────────────
@settings_bp.route('', methods=['POST'])
@login_required
@admin_required
def save_settings():
    """Lưu cài đặt Telegram và IoT vào database."""
    from app.models.setting import SystemSetting

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Thiếu dữ liệu'}), 400

    saved = []

    # Telegram Token — chỉ lưu nếu không phải masked value
    if 'telegram_token' in data:
        val = data['telegram_token'].strip()
        if val and not val.startswith('*'):   # không lưu giá trị masked
            SystemSetting.set('telegram_token', val)
            saved.append('token')

    # Chat ID
    if 'telegram_chat_id' in data:
        SystemSetting.set('telegram_chat_id', data['telegram_chat_id'].strip())
        saved.append('chat_id')

    # Bật/tắt gửi Telegram
    if 'telegram_enabled' in data:
        SystemSetting.set('telegram_enabled', '1' if data['telegram_enabled'] else '0')
        saved.append('enabled')

    # Khung giờ hoạt động
    if 'telegram_hour_from' in data:
        h = max(0, min(23, int(data['telegram_hour_from'])))
        SystemSetting.set('telegram_hour_from', h)
        saved.append('hour_from')

    if 'telegram_hour_to' in data:
        h = max(0, min(23, int(data['telegram_hour_to'])))
        SystemSetting.set('telegram_hour_to', h)
        saved.append('hour_to')

    # Chế độ gửi Telegram: 'normal' (chỉ text) hoặc 'mandatory' (bắt buộc kèm ảnh)
    if 'telegram_send_mode' in data:
        mode = data['telegram_send_mode']
        if mode in ('normal', 'mandatory'):
            SystemSetting.set('telegram_send_mode', mode)
            saved.append('send_mode')

    # ── Cấu hình IoT ──
    if 'iot_enabled' in data:
        SystemSetting.set('iot_enabled', '1' if data['iot_enabled'] else '0')
        saved.append('iot_enabled')

    if 'iot_esp32_ip' in data:
        SystemSetting.set('iot_esp32_ip', data['iot_esp32_ip'].strip())
        saved.append('iot_esp32_ip')

    if 'iot_alert_devices' in data:
        SystemSetting.set('iot_alert_devices', data['iot_alert_devices'].strip())
        saved.append('iot_alert_devices')

    if 'iot_buzzer_duration' in data:
        d_val = max(1, min(60, int(data['iot_buzzer_duration'])))
        SystemSetting.set('iot_buzzer_duration', d_val)
        saved.append('iot_buzzer_duration')

    log_audit('UPDATE_SETTINGS', 'SystemSetting', None, {'saved_fields': saved})
    return jsonify({'message': f'Đã lưu: {", ".join(saved)}', 'saved': saved})


# ── Test kết nối Telegram ─────────────────────────────────
@settings_bp.route('/test_telegram', methods=['POST'])
@login_required
@admin_required
def test_telegram():
    """Gửi tin nhắn test để kiểm tra Token và Chat ID."""
    from app.models.setting import SystemSetting
    from app.services.telegram_service import test_connection
    import os

    # Ưu tiên token trong request, nếu không có thì lấy từ DB/env
    data    = request.get_json() or {}
    token   = data.get('token',   '').strip()
    chat_id = data.get('chat_id', '').strip()

    if not token or token.startswith('*'):
        token = SystemSetting.get('telegram_token') or os.getenv('TELEGRAM_BOT_TOKEN', '')
    if not chat_id:
        chat_id = SystemSetting.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID', '')

    if not token:
        return jsonify({'success': False, 'message': 'Chưa có Bot Token'}), 400
    if not chat_id:
        return jsonify({'success': False, 'message': 'Chưa có Chat ID'}), 400

    ok, msg = test_connection(token, chat_id)
    return jsonify({'success': ok, 'message': msg})

@settings_bp.route('/test_stoop_alert', methods=['POST'])
@login_required
@admin_required
def test_stoop_alert():
    """
    Tạo sự kiện giả lập vi phạm 'Cúi người' (Stoop Pose) trong vùng nguy cơ ROI
    và gửi ngay cảnh báo kèm hình ảnh chứng cứ qua Telegram Bot (Ban Ban).
    """
    import cv2
    import numpy as np
    from app import db
    from app.models.event import Event
    from app.models.roi import ROI
    from app.services.telegram_service import send_alert, _get_config

    cfg = _get_config()
    if not cfg['token'] or not cfg['chat_id']:
        return jsonify({'success': False, 'message': 'Chưa cấu hình Telegram Token hoặc Chat ID trong Hệ thống.'}), 400

    # Lấy hoặc tạo ROI giả lập
    roi_obj = ROI.query.first()
    roi_name = roi_obj.name if roi_obj else "Vùng Gầm Bàn Case #01"

    from datetime import datetime, timedelta

    # Tạo Event giả lập vi phạm tư thế Cúi người
    event = Event(
        roi_id=roi_obj.id if roi_obj else None,
        roi_name=roi_name,
        pose='Cui nguoi',
        level='medium',
        person_count=1,
        camera_id=1,
        started_at=datetime.utcnow() - timedelta(seconds=8)
    )
    db.session.add(event)
    db.session.commit()

    # Tạo frame giả lập có đè thông tin cảnh báo "CÚI NGƯỜI BẤT THƯỜNG"
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    # Background màu tối
    img[:] = (30, 30, 30)
    # Vẽ ô vùng ROI đỏ
    cv2.rectangle(img, (100, 100), (540, 380), (0, 0, 255), 2)
    cv2.putText(img, "ROI: VUNG GAM BAN CASE #01", (110, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    # Vẽ khung người mô phỏng cúi người
    cv2.circle(img, (280, 200), 20, (0, 255, 255), -1) # Head
    cv2.line(img, (280, 220), (360, 280), (0, 255, 255), 4) # Spine stooping
    cv2.line(img, (360, 280), (380, 360), (0, 255, 255), 4) # Legs
    # Gán nhãn cảnh báo
    cv2.rectangle(img, (120, 120), (520, 170), (0, 0, 180), -1)
    cv2.putText(img, "CANH BAO: CUI NGUOI TRONG ROI (>8s)", (130, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    _, buf = cv2.imencode('.jpg', img)
    frame_bytes = buf.tobytes()

    # Gửi alert Telegram qua thread
    send_alert(event, frame_bytes=frame_bytes)

    return jsonify({
        'success': True,
        'message': f'Đã phát lệnh gửi Cảnh báo vi phạm CÚI NGƯỜI (Event #{event.id}) tới Telegram!',
        'event_id': event.id
    })


# ── System Metrics ───────────────────────────────────────
@settings_bp.route('/metrics', methods=['GET'])
@login_required
def get_metrics():
    """Trả về thông số hiệu năng hệ thống (CPU, RAM, Disk, Active Threads & Camera Stream Stability)."""
    from app.services.system_service import get_system_metrics
    from app.services.camera_service import camera_manager

    metrics = get_system_metrics()
    metrics['camera_stats'] = camera_manager.get_all_stats()
    return jsonify(metrics)


# ── Export System Configuration ───────────────────────────
@settings_bp.route('/export', methods=['GET'])
@login_required
@admin_required
def export_config():
    """Xuất toàn bộ cấu hình hệ thống (Phòng, Camera, ROI, IoT, Máy tính, Settings) ra JSON."""
    from app.models.room import Room
    from app.models.camera import Camera
    from app.models.computer import Computer
    from app.models.iot_device import IoTDevice
    from app.models.roi import ROI
    from app.models.setting import SystemSetting

    rooms = Room.query.all()
    cameras = Camera.query.all()
    computers = Computer.query.all()
    iot_devices = IoTDevice.query.all()
    rois = ROI.query.all()
    settings = SystemSetting.query.all()

    config_package = {
        'exported_at': str(request.args.get('t', '')),
        'rooms': [r.to_dict() for r in rooms],
        'cameras': [c.to_dict() for c in cameras],
        'computers': [cp.to_dict() for cp in computers],
        'iot_devices': [dev.to_dict() for dev in iot_devices],
        'rois': [r.to_dict() for r in rois],
        'settings': [{'key': s.key, 'value': s.value if not s.key.endswith('token') else '***'} for s in settings]
    }
    return jsonify(config_package)


# ── Import System Configuration ───────────────────────────
@settings_bp.route('/import', methods=['POST'])
@login_required
@admin_required
def import_config():
    """Khôi phục cấu hình hệ thống từ file JSON."""
    from app import db
    from app.models.room import Room
    from app.models.camera import Camera
    from app.models.computer import Computer
    from app.models.iot_device import IoTDevice
    from app.models.roi import ROI
    from app.models.setting import SystemSetting

    data = request.get_json()
    if not data or 'rooms' not in data:
        return jsonify({'error': 'File cấu hình không hợp lệ'}), 400

    try:
        # Import Rooms
        for r_data in data.get('rooms', []):
            existing = Room.query.filter_by(name=r_data['name']).first()
            if not existing:
                room = Room(name=r_data['name'], location=r_data.get('location'), is_active=r_data.get('is_active', True))
                db.session.add(room)
        db.session.commit()

        # Import Settings
        for s_data in data.get('settings', []):
            k, v = s_data.get('key'), s_data.get('value')
            if k and v and not v.startswith('*'):
                SystemSetting.set(k, v)

        log_audit('IMPORT_CONFIG', 'SystemSetting', None, {'imported_keys': len(data.get('settings', []))})
        return jsonify({'success': True, 'message': 'Đã khôi phục cấu hình thành công!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Lỗi khi nhập cấu hình: {str(e)}'}), 500

