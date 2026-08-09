# ============================================================
# app/services/esp32_service.py — Điều khiển thiết bị IoT (ESP32)
#
# Quản lý giao tiếp HTTP REST API tới ESP32 (Thật & Giả lập).
# Theo dõi heartbeat trạng thái Online/Offline của thiết bị.
# ============================================================
import os
import time
import logging
import threading
import requests

logger = logging.getLogger(__name__)

# Cache lưu trữ trạng thái thiết bị trong memory để phản hồi nhanh UI
_iot_status_cache = {
    'ip': None,
    'last_seen': 0.0,
    'devices': {
        'led': 0,
        'buzzer': 0,
        'relay': 0
    },
    'sensors': {
        'temperature': 28.5,
        'humidity': 65.0,
        'smoke': 0,        # 0: Bình thường, 1: Có khói/khí ga
        'door_closed': 1   # 1: Đóng, 0: Mở
    }
}
_cache_lock = threading.Lock()
_last_emergency_time = 0.0

# ─── Đọc cấu hình từ DB ────────────────────────────────────
def _get_iot_config() -> dict:
    """Lấy cấu hình IoT từ database (bảng system_settings)."""
    try:
        from app.models.setting import SystemSetting
        enabled = SystemSetting.get_bool('iot_enabled', default=False)
        esp32_ip = SystemSetting.get('iot_esp32_ip') or 'http://127.0.0.1:5000/mock_esp32'
        devices = SystemSetting.get('iot_alert_devices') or 'led,buzzer,relay'
        buzzer_dur = SystemSetting.get_int('iot_buzzer_duration', default=10)
    except Exception:
        enabled = False
        esp32_ip = 'http://127.0.0.1:5000/mock_esp32'
        devices = 'led,buzzer,relay'
        buzzer_dur = 10

    return {
        'enabled': enabled,
        'esp32_ip': esp32_ip.strip(),
        'devices': [d.strip() for d in devices.split(',') if d.strip()],
        'buzzer_dur': buzzer_dur
    }

# ─── Ghi nhận Heartbeat từ ESP32 ─────────────────────────
def register_heartbeat(ip: str, payload: dict):
    """
    Được gọi khi ESP32 (thật hoặc giả lập) gửi heartbeat POST /api/iot/heartbeat.
    Cập nhật thời gian nhìn thấy cuối cùng, trạng thái relay/led/còi và thông số cảm biến.
    """
    global _last_emergency_time
    with _cache_lock:
        _iot_status_cache['ip'] = ip
        _iot_status_cache['last_seen'] = time.time()
        
        # Nếu payload truyền dạng {'devices': {...}, 'sensors': {...}} hoặc truyền trực tiếp
        device_states = payload.get('devices') if isinstance(payload, dict) and 'devices' in payload else payload
        if isinstance(device_states, dict):
            for k, v in device_states.items():
                if k in _iot_status_cache['devices']:
                    _iot_status_cache['devices'][k] = int(v)

        sensors = payload.get('sensors') if isinstance(payload, dict) else None
        if isinstance(sensors, dict):
            for sk in ['temperature', 'humidity', 'smoke', 'door_closed']:
                if sk in sensors:
                    _iot_status_cache['sensors'][sk] = sensors[sk]

        # Kiểm tra ngưỡng khẩn cấp (Cháy/Khói hoặc Nhiệt độ quá cao > 45°C)
        curr_smoke = _iot_status_cache['sensors']['smoke']
        curr_temp = _iot_status_cache['sensors']['temperature']

    # Cooldown 30s cho cảnh báo khẩn cấp
    if (curr_smoke == 1 or curr_temp > 45.0) and (time.time() - _last_emergency_time > 30.0):
        _last_emergency_time = time.time()
        _trigger_fire_alarm(curr_smoke, curr_temp, ip)

    logger.debug(f"[IoT] Nhan heartbeat tu {ip}")

def _trigger_fire_alarm(smoke: int, temp: float, ip: str):
    """Tự động kích hoạt còi hú ESP32 và gửi Telegram khi có sự cố cháy khói."""
    from app.services.telegram_service import send_message, _get_config
    logger.warning(f"🚨 [CẢNH BÁO CHÁY/KHÓI] ESP32 {ip}: Temp={temp}°C, Smoke={smoke}")
    send_iot_command('buzzer', 1, duration=15)
    send_iot_command('led', 1, duration=15)
    
    cfg = _get_config()
    if cfg['token'] and cfg['chat_id']:
        msg = (
            f"🔥 <b>CẢNH BÁO NGUY HIỂM CHÁY / KHÓI</b> 🔥\n\n"
            f"📍 <b>Nguồn phát:</b> Nút ESP32 (IP: {ip})\n"
            f"🌡 <b>Nhiệt độ hiện tại:</b> {temp}°C\n"
            f"💨 <b>Cảm biến khói:</b> {'PHÁT HIỆN KHÓI' if smoke == 1 else 'Bình thường'}\n"
            f"🚨 <b>Hành động:</b> Đã kích hoạt còi hú và đèn báo động!"
        )
        t = threading.Thread(target=send_message, args=(cfg['token'], cfg['chat_id'], msg), daemon=True)
        t.start()

# ─── Lấy trạng thái hoạt động hiện tại ────────────────────
def get_iot_status() -> dict:
    """
    Trả về trạng thái hoạt động hiện tại của thiết bị IoT để hiển thị trên UI.
    """
    cfg = _get_iot_config()
    with _cache_lock:
        last_seen = _iot_status_cache['last_seen']
        time_diff = time.time() - last_seen
        is_online = (last_seen > 0) and (time_diff < 25.0)

        current_ip = _iot_status_cache['ip'] if is_online else None
        device_states = dict(_iot_status_cache['devices']) if is_online else {'led': 0, 'buzzer': 0, 'relay': 0}
        sensor_states = dict(_iot_status_cache['sensors'])

    return {
        'enabled': cfg['enabled'],
        'esp32_ip': cfg['esp32_ip'],
        'is_online': is_online,
        'last_seen_seconds_ago': int(time_diff) if last_seen > 0 else -1,
        'ip': current_ip,
        'devices': device_states,
        'sensors': sensor_states
    }

# ─── Gửi lệnh điều khiển HTTP tới ESP32 ──────────────────
def send_iot_command(device_type: str, status: int, duration: int = 0) -> bool:
    """
    Gửi lệnh điều khiển thiết bị tới ESP32 qua HTTP POST.
    Chạy bất đồng bộ trong background thread để không chặn Flask/Camera.

    Args:
        device_type: 'led', 'buzzer', hoặc 'relay'
        status: 1 (bật), 0 (tắt)
        duration: thời gian duy trì giây (chỉ áp dụng với còi/đèn nếu muốn tự tắt)
    """
    cfg = _get_iot_config()
    if not cfg['enabled']:
        logger.debug(f"[IoT] Da tat tinh nang IoT — bo qua lenh {device_type}={status}")
        return False

    endpoint = f"{cfg['esp32_ip']}/control"

    def _post_request():
        payload = {
            'device': device_type,
            'status': status,
            'duration': duration
        }
        try:
            logger.info(f"[IoT] Dang gui lenh den {endpoint}: {payload}")
            resp = requests.post(endpoint, json=payload, timeout=5)
            resp.raise_for_status()
            logger.info(f"[IoT] Gui lenh thanh cong. Phan hoi: {resp.text}")
            
            # Cập nhật tạm trạng thái vào cache để UI đổi trạng thái ngay lập tức
            with _cache_lock:
                if device_type in _iot_status_cache['devices']:
                    _iot_status_cache['devices'][device_type] = status
            return True
        except requests.RequestException as e:
            logger.error(f"[IoT] Loi ket noi toi ESP32 tai {endpoint}: {e}")
            return False

    t = threading.Thread(target=_post_request, daemon=True, name=f"iot-cmd-{device_type}")
    t.start()
    return True

# ─── Kích hoạt cảnh báo tự động khi có sự kiện vi phạm ────
def trigger_alert_hardware(event):
    """
    Được gọi bởi Alert Engine khi phát hiện vi phạm tư thế mới trong ROI.
    Bật còi buzzer kêu 10 giây (hoặc theo cấu hình) và nhấp nháy đèn LED/Relay.
    """
    cfg = _get_iot_config()
    if not cfg['enabled']:
        return

    logger.info(f"[IoT] Kich hoat thiet bi canh bao cho Event #{event.id}")

    # Bật buzzer (kêu trong thời gian cấu hình, ví dụ 10s rồi tự tắt)
    if 'buzzer' in cfg['devices']:
        send_iot_command('buzzer', 1, duration=cfg['buzzer_dur'])

    # Bật LED
    if 'led' in cfg['devices']:
        send_iot_command('led', 1, duration=cfg['buzzer_dur'])

    # Đóng Relay
    if 'relay' in cfg['devices']:
        send_iot_command('relay', 1, duration=0) # Relay bật đến khi có lệnh tắt hoặc hết vi phạm
