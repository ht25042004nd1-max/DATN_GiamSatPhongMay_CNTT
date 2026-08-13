# ============================================================
# app/services/telegram_service.py — Gửi cảnh báo qua Telegram Bot API
#
# Sử dụng thư viện `requests` thuần (không dùng python-telegram-bot)
# để tránh phụ thuộc vào asyncio và đơn giản hóa tích hợp.
#
# Pipeline gửi cảnh báo:
#   AlertEngine tạo Event → _send_alert() → telegram_service.send_alert()
#   → sendMessage + sendPhoto (Telegram Bot API)
# ============================================================
import os
import time
import logging
import threading
import requests
from datetime import datetime, time as dtime
from io import BytesIO

logger = logging.getLogger(__name__)

# Base URL của Telegram Bot API
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Timeout cho mỗi request gửi Telegram (giây)
REQUEST_TIMEOUT = 10

# ─── Emoji theo mức độ cảnh báo ───────────────────────────
LEVEL_EMOJI = {
    'high':   '🔴',
    'medium': '🟠',
    'low':    '🟡',
}
POSE_VN = {
    'Quy':       'Quỳ',
    'Ngoi':      'Ngồi',
    'Cui nguoi': 'Cúi người',
    'Dung':      'Đứng',
}


# ─── Hàm phụ trợ ──────────────────────────────────────────
def _clean_token(token: str) -> str:
    """Xóa khoảng trắng, ký tự đặc biệt ẩn và tiền tố 'bot' nếu người dùng lỡ nhập vào."""
    if not token:
        return ""
    # Loại bỏ tất cả khoảng trắng (gồm cả khoảng trắng giữa, tab, xuống dòng)
    token = "".join(token.split())
    # Loại bỏ các ký tự đặc biệt ẩn như Zero-width space nếu có
    token = token.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
    
    if token.lower().startswith('bot'):
        token = token[3:]
    return token


# ─── Đọc cấu hình từ DB (ưu tiên) hoặc .env (fallback) ──
def _get_config() -> dict:
    """
    Đọc cấu hình Telegram từ database, fallback sang .env nếu chưa có.

    Ưu tiên: DB (SystemSetting) > .env > None
    """
    try:
        from app.models.setting import SystemSetting
        token   = SystemSetting.get('telegram_token') or os.getenv('TELEGRAM_BOT_TOKEN', '')
        chat_id = SystemSetting.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID', '')
        enabled = SystemSetting.get_bool('telegram_enabled', default=False)
        hour_from = SystemSetting.get_int('telegram_hour_from', default=0)
        hour_to   = SystemSetting.get_int('telegram_hour_to',   default=23)
    except Exception:
        # Trường hợp DB chưa có bảng (lần chạy đầu)
        token     = os.getenv('TELEGRAM_BOT_TOKEN', '')
        chat_id   = os.getenv('TELEGRAM_CHAT_ID', '')
        enabled   = False
        hour_from = 0
        hour_to   = 23

    return {
        'token':      _clean_token(token),
        'chat_id':    chat_id.strip() if chat_id else '',
        'enabled':    enabled,
        'hour_from':  hour_from,
        'hour_to':    hour_to,
        # Chế độ gửi: 'normal' = chỉ text | 'mandatory' = bắt buộc kèm ảnh
        'send_mode':  SystemSetting.get('telegram_send_mode', 'mandatory') if 'SystemSetting' in dir() else 'mandatory',
    }


# ─── Kiểm tra khung giờ hoạt động ────────────────────────
def _in_active_hours(hour_from: int, hour_to: int) -> bool:
    """
    Kiểm tra giờ hiện tại có trong khung giờ gửi cảnh báo không.
    Ví dụ: hour_from=7, hour_to=17 → chỉ gửi 07:00–17:59.
    """
    now_hour = datetime.now().hour
    if hour_from <= hour_to:
        return hour_from <= now_hour <= hour_to
    else:
        # Qua đêm (VD: 22–06): từ 22 đến 06 sáng hôm sau
        return now_hour >= hour_from or now_hour <= hour_to


# ─── Gửi text message ─────────────────────────────────────
def send_message(token: str, chat_id: str, text: str) -> bool:
    """
    Gửi tin nhắn văn bản qua Telegram Bot API.
    Trả về True nếu thành công.
    """
    token = _clean_token(token)
    url = TELEGRAM_API.format(token=token, method='sendMessage')
    try:
        resp = requests.post(url, json={
            'chat_id':    chat_id,
            'text':       text,
            'parse_mode': 'HTML',
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not data.get('ok'):
            logger.error(f"[Telegram] sendMessage that bai: {data}")
            return False
        return True
    except requests.RequestException as e:
        logger.error(f"[Telegram] Loi ket noi sendMessage: {e}")
        return False


# ─── Gửi ảnh kèm caption ─────────────────────────────────
def send_photo(token: str, chat_id: str, photo_bytes: bytes, caption: str) -> bool:
    """
    Gửi ảnh JPEG kèm caption qua Telegram Bot API.
    Trả về True nếu thành công.
    """
    token = _clean_token(token)
    url = TELEGRAM_API.format(token=token, method='sendPhoto')
    try:
        resp = requests.post(url, data={
            'chat_id':    chat_id,
            'caption':    caption,
            'parse_mode': 'HTML',
        }, files={
            'photo': ('alert.jpg', BytesIO(photo_bytes), 'image/jpeg'),
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not data.get('ok'):
            logger.error(f"[Telegram] sendPhoto that bai: {data}")
            return False
        return True
    except requests.RequestException as e:
        logger.error(f"[Telegram] Loi ket noi sendPhoto: {e}")
        return False


# ─── Test kết nối ─────────────────────────────────────────
def test_connection(token: str, chat_id: str) -> tuple[bool, str]:
    """
    Gửi tin nhắn test để xác nhận Token và Chat ID đúng.
    Trả về (True, 'OK') hoặc (False, 'thông báo lỗi').
    """
    token = _clean_token(token)
    # In thông tin debug ra console để người dùng kiểm tra trên Terminal
    masked_token = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else token
    print(f"\n[TELEGRAM DEBUG] Đang test kết nối. Token sử dụng: '{masked_token}' (độ dài: {len(token)}) | Chat ID: '{chat_id}'")
    
    url = TELEGRAM_API.format(token=token, method='getMe')
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return False, f"Lỗi 404 từ Telegram API (Không tìm thấy URL). Token đang kiểm thử: '{masked_token}' (Độ dài: {len(token)} ký tự). Hãy chắc chắn bạn đã nhập đúng định dạng Token từ @BotFather (ví dụ: '123456789:ABCdef...')."
        elif resp.status_code == 401:
            return False, f"Lỗi 401: Token không hợp lệ hoặc đã hết hạn (Unauthorized). Token đang kiểm thử: '{masked_token}' (Độ dài: {len(token)} ký tự). Vui lòng kiểm tra lại cấu hình."
        
        resp.raise_for_status()
        bot_data = resp.json()
        if not bot_data.get('ok'):
            return False, f"Lỗi từ Telegram: {bot_data.get('description', bot_data)} | Token: '{masked_token}'"

        bot_name = bot_data['result'].get('username', '?')
        ok = send_message(token, chat_id,
            f"✅ <b>Lab Monitor — Kết nối thành công!</b>\n"
            f"Bot: @{bot_name}\n"
            f"Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        if ok:
            return True, f"Kết nối thành công với @{bot_name}"
        return False, "Token OK nhưng không gửi được tới Chat ID. Kiểm tra Chat ID và quyền bot trong group."
    except requests.RequestException as e:
        return False, f"Lỗi kết nối: {str(e)}"


# ─── Hàm chính: gửi cảnh báo Event ────────────────────────────
def send_alert(event, frame_bytes: bytes = None, send_mode: str = None):
    """
    Gửi cảnh báo Telegram khi có Event mới.
    
    Chế độ gửi (send_mode):
      - 'normal'    : Chỉ gửi tin nhắn text (không kèm hình ảnh)
      - 'mandatory' : Bắt buộc gửi kèm hình ảnh minh chứng
    Nếu send_mode=None: đọc từ cấu hình DB.
    """
    cfg = _get_config()
    if not cfg['enabled'] or not cfg['token'] or not cfg['chat_id']:
        return
    if not _in_active_hours(cfg['hour_from'], cfg['hour_to']):
        return

    # Xác định chế độ gửi
    effective_mode = send_mode or cfg.get('send_mode', 'mandatory')

    emoji     = LEVEL_EMOJI.get(event.level, '⚠️')
    pose_vn   = POSE_VN.get(event.pose, event.pose)
    dur_str   = f"{event.duration_seconds}s" if event.duration_seconds < 60 \
                else f"{event.duration_seconds // 60}p{event.duration_seconds % 60}s"
    timestamp = event.started_at.strftime('%d/%m/%Y %H:%M:%S') if event.started_at else '?'

    # Biểu tượng chế độ gửi
    mode_label = '📷 Kèm ảnh' if effective_mode == 'mandatory' else '📝 Chỉ text'

    caption = (
        f"{emoji} <b>CẢNH BÁO — {event.level_label.upper()}</b>\n\n"
        f"📍 <b>ROI:</b> {event.roi_name or 'N/A'}\n"
        f"🤸 <b>Tư thế:</b> {pose_vn}\n"
        f"⏱ <b>Duy trì:</b> {dur_str}\n"
        f"🕐 <b>Thời gian:</b> {timestamp}\n"
        f"👥 <b>Số người:</b> {event.person_count}\n"
        f"📒 <b>Chế độ gửi:</b> {mode_label}\n"
        f"🔖 <b>Mã sự kiện:</b> #{event.id}"
    )

    def _do_send():
        try:
            if effective_mode == 'mandatory' and frame_bytes:
                # Chế độ BẮt BUỘC: luôn gửi kèm ảnh
                ok = send_photo(cfg['token'], cfg['chat_id'], frame_bytes, caption)
                if not ok:
                    # Fallback: gửi text nếu gửi ảnh thất bại
                    send_message(cfg['token'], cfg['chat_id'],
                                 caption + "\n\n⚠️ <i>Lỗi gửi ảnh, chỉ gửi text</i>")
            else:
                # Chế độ THƯỜNG: chỉ gửi text
                send_message(cfg['token'], cfg['chat_id'], caption)
        except Exception as e:
            logger.error(f"[Telegram] Loi khi gui Event #{event.id}: {e}")

    t = threading.Thread(target=_do_send, daemon=True, name=f"tg-alert-{event.id}")
    t.start()


# ─── Long Polling (Luôn Kết Nối) ──────────────────────────
_bot_running = False
def start_polling():
    global _bot_running
    if _bot_running: return
    _bot_running = True

    def poll():
        last_update_id = 0
        while _bot_running:
            try:
                cfg = _get_config()
                if not cfg['enabled'] or not cfg['token']:
                    time.sleep(10)
                    continue
                
                url = TELEGRAM_API.format(token=cfg['token'], method='getUpdates')
                resp = requests.get(url, params={'offset': last_update_id + 1, 'timeout': 30}, timeout=35)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('ok'):
                        for update in data.get('result', []):
                            last_update_id = update['update_id']
                            msg = update.get('message', {})
                            text = msg.get('text', '').strip()
                            chat_id = str(msg.get('chat', {}).get('id', ''))
                            if text == '/status':
                                send_message(cfg['token'], chat_id, "✅ <b>Lab Monitor Bot đang hoạt động!</b>\nHệ thống đang ở trạng thái LUÔN KẾT NỐI để nhận cảnh báo.")
                            elif text == '/help':
                                send_message(cfg['token'], chat_id, "ℹ️ <b>Danh sách lệnh:</b>\n/status - Kiểm tra trạng thái\n/help - Trợ giúp")
            except Exception as e:
                time.sleep(5) # Tránh loop quá nhanh khi rớt mạng

    t = threading.Thread(target=poll, daemon=True, name="tg-polling")
    t.start()
    logger.info("[Telegram] Long Polling (luôn kết nối) đã được khởi động.")


# ─── Tiện ích: gửi tin nhắn đơn giản không cần truyền token ─
def send_simple_message(text: str) -> bool:
    """
    Hàm tiện ích: gửi tin nhắn text lấy cấu hình token/chat_id từ DB tự động.
    Dùng cho các service nội bộ (PingService, HealthCheck, ...).
    """
    try:
        cfg = _get_config()
        if not cfg['token'] or not cfg['chat_id']:
            logger.warning("[Telegram] send_simple_message: chưa cấu hình token/chat_id")
        # Chuyển Markdown (*bold*) sang HTML (<b>bold</b>) an toàn
        import re
        html_text = re.sub(r'\*(.*?)\*', r'<b>\1</b>', text)
        return send_message(cfg['token'], cfg['chat_id'], html_text)
    except Exception as e:
        logger.error(f"[Telegram] send_simple_message lỗi: {e}")
        return False

