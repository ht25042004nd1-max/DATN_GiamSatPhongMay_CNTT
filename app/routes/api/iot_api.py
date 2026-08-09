# ============================================================
# app/routes/iot_routes.py — Routes cho quản lý thiết bị IoT
#
# Cung cấp các API cập nhật trạng thái thiết bị và Endpoint giả lập ESP32.
# ============================================================
import time
import threading
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app import db
from app.utils.decorators import admin_required
from app.services.esp32_service import register_heartbeat, get_iot_status, send_iot_command

iot_bp = Blueprint('iot', __name__)

# ─── Trạng thái lưu trữ của ESP32 Giả lập ──────────────────
_mock_esp32_state = {
    'led': 0,
    'buzzer': 0,
    'relay': 0,
    'buzzer_timeout': 0.0,
    'led_timeout': 0.0
}
_mock_lock = threading.Lock()

# Thread chạy ngầm mô phỏng việc đếm ngược tắt buzzer/led của ESP32 giả lập
def _mock_device_scheduler():
    while True:
        time.sleep(1.0)
        with _mock_lock:
            now = time.time()
            if _mock_esp32_state['buzzer'] == 1 and now > _mock_esp32_state['buzzer_timeout']:
                _mock_esp32_state['buzzer'] = 0
                print("[Mock ESP32] Buzzer da tu dong tat sau timeout (10s)")
            if _mock_esp32_state['led'] == 1 and now > _mock_esp32_state['led_timeout']:
                _mock_esp32_state['led'] = 0
                print("[Mock ESP32] LED da tu dong tat sau timeout (10s)")

# Khởi chạy scheduler mô phỏng ESP32 giả lập
t = threading.Thread(target=_mock_device_scheduler, daemon=True, name="mock-esp32-scheduler")
t.start()

# Thread giả lập gửi heartbeat từ ESP32 ảo đến Flask server mỗi 10 giây
def _mock_heartbeat_sender():
    # Đợi app khởi chạy xong
    time.sleep(3.0)
    import requests
    while True:
        try:
            # Gửi heartbeat tới Flask server chính
            with _mock_lock:
                states = {
                    'led': _mock_esp32_state['led'],
                    'buzzer': _mock_esp32_state['buzzer'],
                    'relay': _mock_esp32_state['relay']
                }
            # Sử dụng localhost:5000 để post dữ liệu heartbeat
            requests.post('http://127.0.0.1:5000/api/iot/heartbeat', json={
                'ip': '127.0.0.1 (Gia lap)',
                'devices': states
            }, timeout=2)
        except Exception:
            pass
        time.sleep(10.0)

t_hb = threading.Thread(target=_mock_heartbeat_sender, daemon=True, name="mock-esp32-heartbeat")
t_hb.start()


# ─── PHẦN A: API Cổng kết nối & Trạng thái ──────────────────

@iot_bp.route('/api/iot/heartbeat', methods=['POST'])
def iot_heartbeat():
    """
    Heartbeat API: Nhận tín hiệu từ ESP32 gửi lên định kỳ.
    JSON: { "ip": "192.168.1.50", "devices": { "led": 0, "buzzer": 0, "relay": 1 } }
    """
    data = request.get_json() or {}
    ip = data.get('ip', request.remote_addr)
    devices = data.get('devices', {})
    
    register_heartbeat(ip, devices)
    return jsonify({'status': 'ok', 'received_at': time.time()})


@iot_bp.route('/api/iot/status', methods=['GET'])
@login_required
def iot_status():
    """Lấy trạng thái thiết bị IoT hiện tại (dùng để polling từ frontend)."""
    return jsonify(get_iot_status())


@iot_bp.route('/api/iot/control_manual', methods=['POST'])
@login_required
@admin_required
def iot_control_manual():
    """Điều khiển thiết bị thủ công từ UI Admin."""
    data = request.get_json() or {}
    device = data.get('device')
    status = int(data.get('status', 0))
    duration = int(data.get('duration', 0))

    if device not in ['led', 'buzzer', 'relay']:
        return jsonify({'error': 'Thiết bị không hợp lệ'}), 400

    ok = send_iot_command(device, status, duration)
    return jsonify({'success': ok, 'message': f'Đã phát lệnh {device}={status}'})


# ─── PHẦN B: Route của ESP32 Giả lập (Mock ESP32) ───────────

@iot_bp.route('/mock_esp32/control', methods=['POST'])
def mock_esp32_control():
    """
    Endpoint giả lập hoạt động giống hệt ESP32 thật.
    Nhận: { "device": "led", "status": 1, "duration": 10 }
    """
    data = request.get_json() or {}
    device = data.get('device')
    status = int(data.get('status', 0))
    duration = int(data.get('duration', 0))

    if device not in ['led', 'buzzer', 'relay']:
        return jsonify({'error': 'Device invalid'}), 400

    with _mock_lock:
        _mock_esp32_state[device] = status
        if status == 1 and duration > 0:
            timeout_at = time.time() + duration
            if device == 'buzzer':
                _mock_esp32_state['buzzer_timeout'] = timeout_at
            elif device == 'led':
                _mock_esp32_state['led_timeout'] = timeout_at
        
        print(f"[Mock ESP32] Da thay doi trang thai: {device}={status} (Duration: {duration}s)")
        
    return jsonify({
        'status': 'success',
        'device': device,
        'state': status,
        'mock_esp32_states': _mock_esp32_state
    })
