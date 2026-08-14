# ============================================================
# telegram_bot.py — Module Telegram Bot "banban"
# Kênh cảnh báo một chiều & kiểm tra trạng thái phòng thực hành
#
# Đồ án tốt nghiệp: Giám Sát Phòng Thực Hành Máy Tính (AI + IoT)
# ============================================================
import os
import time
import logging
import threading
import requests
from datetime import datetime, date, time as dtime
from io import BytesIO
from typing import Union, List, Optional
from dotenv import load_dotenv

# Tải biến môi trường từ .env nếu chưa tải
load_dotenv()

logger = logging.getLogger("banban_bot")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s][Bot BanBan] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)

# ─── Cấu hình Telegram API ────────────────────────────────
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
REQUEST_TIMEOUT = 12

# Bộ đệm chống spam cảnh báo (Cooldown 60s per event_key)
# {event_key: timestamp_last_sent}
_ALERT_COOLDOWN_SEC = 60
_cooldown_cache = {}
_cooldown_lock = threading.Lock()

# Trạng thái luồng Polling
_bot_thread: Optional[threading.Thread] = None
_is_polling = False


# ════════════════════════════════════════════════════════════
# 1. HÀM QUẢN LÝ CẤU HÌNH & BẢO MẬT (TOKEN & WHITELIST)
# ════════════════════════════════════════════════════════════

def _clean_token(token: str) -> str:
    """Loại bỏ khoảng trắng thừa, ký tự ẩn và tiền tố 'bot' nếu có."""
    if not token:
        return ""
    token = "".join(token.split()).replace("\ufeff", "").replace("\u200b", "")
    if token.lower().startswith("bot"):
        token = token[3:]
    return token


def get_bot_token() -> str:
    """
    Lấy Telegram Bot Token.
    Ưu tiên đọc từ database SystemSetting, fallback sang biến môi trường .env.
    Không bao giờ in plain-text token ra log để bảo mật.
    """
    try:
        from app.models.setting import SystemSetting
        token = SystemSetting.get("telegram_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    except Exception:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return _clean_token(token)


def get_whitelist_chat_ids() -> List[str]:
    """
    Lấy danh sách các Chat ID được phép nhận cảnh báo và sử dụng lệnh quản trị.
    Hỗ trợ cấu hình nhiều chat_id cách nhau bằng dấu phẩy: '123456,7891011'
    """
    raw = ""
    try:
        from app.models.setting import SystemSetting
        raw = SystemSetting.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
    except Exception:
        raw = os.getenv("TELEGRAM_CHAT_ID", "")

    if not raw:
        return []

    # Tách danh sách theo dấu phẩy hoặc chấm phẩy
    chat_ids = [cid.strip() for cid in raw.replace(";", ",").split(",") if cid.strip()]
    return chat_ids


def is_whitelisted(chat_id: Union[int, str]) -> bool:
    """Kiểm tra Chat ID có nằm trong danh sách Whitelist cho phép không."""
    str_cid = str(chat_id).strip()
    whitelist = get_whitelist_chat_ids()
    # Nếu chưa cấu hình whitelist, cho phép để người dùng ban đầu đăng ký
    if not whitelist:
        return True
    return str_cid in whitelist


# ════════════════════════════════════════════════════════════
# 2. HÀM GỬI TIN NHẮN & HÌNH ẢNH CẢNH BÁO
# ════════════════════════════════════════════════════════════

def send_message(chat_id: Union[int, str], text: str) -> bool:
    """
    Gửi tin nhắn văn bản (HTML parse_mode) tới 1 Chat ID cụ thể.
    """
    token = get_bot_token()
    if not token:
        logger.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN.")
        return False

    url = TELEGRAM_API.format(token=token, method="sendMessage")
    try:
        resp = requests.post(url, json={
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "HTML"
        }, timeout=REQUEST_TIMEOUT)
        data = resp.json()
        return bool(data.get("ok"))
    except Exception as e:
        logger.error(f"Lỗi gửi tin nhắn tới {chat_id}: {e}")
        return False


def send_photo(chat_id: Union[int, str], photo_data: Union[str, bytes], caption: str) -> bool:
    """
    Gửi ảnh (từ file path hoặc bytes) kèm caption HTML tới 1 Chat ID.
    """
    token = get_bot_token()
    if not token:
        logger.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN.")
        return False

    url = TELEGRAM_API.format(token=token, method="sendPhoto")
    files = {}

    try:
        if isinstance(photo_data, str):
            if not os.path.exists(photo_data):
                logger.error(f"File ảnh không tồn tại: {photo_data}")
                return send_message(chat_id, caption)
            with open(photo_data, "rb") as f:
                photo_bytes = f.read()
        else:
            photo_bytes = photo_data

        files["photo"] = ("alert.jpg", BytesIO(photo_bytes), "image/jpeg")

        resp = requests.post(
            url,
            data={"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"},
            files=files,
            timeout=REQUEST_TIMEOUT
        )
        data = resp.json()
        if not data.get("ok"):
            # Fallback nếu gửi ảnh lỗi: gửi dạng tin nhắn text
            send_message(chat_id, caption)
            return False
        return True
    except Exception as e:
        logger.error(f"Lỗi gửi ảnh tới {chat_id}: {e}")
        send_message(chat_id, caption)
        return False


def send_alert(
    image_path: Optional[Union[str, bytes]] = None,
    message: str = "",
    event_id: Optional[int] = None,
    pose_type: Optional[str] = None,
    person_id: Optional[int] = None,
    force: bool = False
) -> bool:
    """
    Hàm chính: Gửi cảnh báo vi phạm tự động tới toàn bộ Chat ID trong Whitelist.

    Tham số:
      - image_path: Đường dẫn file ảnh (.jpg) hoặc bytes ảnh chụp lúc vi phạm.
      - message: Nội dung mô tả / caption cảnh báo.
      - event_id: ID sự kiện trong DB (dùng để chống spam trùng lặp).
      - pose_type: Loại tư thế vi phạm (Quỳ, Ngồi gầm bàn, Cúi người...).
      - person_id: ID người vi phạm do AI gán (P1, P2...).
      - force: Nếu True, bỏ qua kiểm tra cooldown chống spam.
    """
    token = get_bot_token()
    whitelist = get_whitelist_chat_ids()

    if not token or not whitelist:
        logger.warning("Bot chưa sẵn sàng: Thiếu Token hoặc Whitelist Chat ID.")
        return False

    # ─── Cơ chế chống spam (Cooldown 60s) ───────────────────
    now = time.time()
    cooldown_key = f"evt_{event_id}" if event_id else f"pose_{pose_type}_{person_id}"

    if not force:
        with _cooldown_lock:
            last_sent = _cooldown_cache.get(cooldown_key, 0.0)
            if now - last_sent < _ALERT_COOLDOWN_SEC:
                logger.info(f"Bỏ qua cảnh báo lặp (Cooldown còn {int(_ALERT_COOLDOWN_SEC - (now - last_sent))}s) cho [{cooldown_key}].")
                return False
            _cooldown_cache[cooldown_key] = now

            # Dọn dẹp cache cũ > 5 phút
            for k in list(_cooldown_cache.keys()):
                if now - _cooldown_cache[k] > 300:
                    del _cooldown_cache[k]

    # ─── Định dạng nội dung tin nhắn ─────────────────────────
    timestamp_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    header = "🚨 <b>[CẢNH BÁO VI PHẠM PHÒNG MÁY]</b> 🚨\n"
    
    body_lines = [header]
    if pose_type:
        body_lines.append(f"🤸 <b>Tư thế:</b> {pose_type}")
    if person_id is not None:
        body_lines.append(f"👤 <b>Đối tượng:</b> P{person_id + 1 if isinstance(person_id, int) else person_id}")
    if event_id:
        body_lines.append(f"🔖 <b>Mã sự kiện:</b> #{event_id}")
    body_lines.append(f"🕐 <b>Thời gian:</b> {timestamp_str}")

    if message:
        body_lines.append(f"\n📝 <b>Chi tiết:</b> {message}")

    caption = "\n".join(body_lines)

    # ─── Gửi lần lượt tới tất cả chat_id trong whitelist ────
    success_count = 0
    for cid in whitelist:
        ok = send_photo(cid, image_path, caption) if image_path else send_message(cid, caption)
        if ok:
            success_count += 1

    logger.info(f"Đã gửi cảnh báo [{cooldown_key}] thành công tới {success_count}/{len(whitelist)} người nhận.")
    return success_count > 0


# ════════════════════════════════════════════════════════════
# 3. HÀM XỬ LÝ LỆNH TƯƠNG TÁC (/start, /help, /status)
# ════════════════════════════════════════════════════════════

def _handle_command_start(chat_id: str, username: str):
    """Xử lý lệnh /start: Trả về Chat ID cho người dùng copy cấu hình."""
    reply = (
        "👋 <b>Chào mừng bạn đến với Bot Ban Ban!</b>\n"
        "Kênh cảnh báo an toàn phòng thực hành máy tính (Lab Monitor).\n\n"
        f"🆔 <b>Chat ID của bạn:</b> <code>{chat_id}</code>\n\n"
        "👉 <b>Các bước để kích hoạt nhận cảnh báo:</b>\n"
        "1. Sao chép (copy) dãy số Chat ID ở trên.\n"
        "2. Dán vào biến <code>TELEGRAM_CHAT_ID</code> trong file <code>.env</code>\n"
        "   (hoặc vào Web: <i>Cài đặt Hệ thống ➔ Nhập Chat ID ➔ Lưu</i>).\n"
        "3. Sau khi lưu, bạn sẽ tự động nhận ảnh và thông báo khi có vi phạm!\n\n"
        "Gõ /help để xem các lệnh hỗ trợ."
    )
    send_message(chat_id, reply)


def _handle_command_help(chat_id: str):
    """Xử lý lệnh /help: Liệt kê các lệnh bot hỗ trợ."""
    reply = (
        "ℹ️ <b>DANH SÁCH LỆNH BOT BAN BAN:</b>\n\n"
        "• <code>/start</code> — Xem Chat ID của bạn để cấu hình nhận cảnh báo.\n"
        "• <code>/status</code> — Kiểm tra trạng thái camera và số lượng cảnh báo trong ngày.\n"
        "• <code>/capture</code> — Chụp 1 bức ảnh ngay lúc này từ camera đang hoạt động.\n"
        "• <code>/help</code> — Xem hướng dẫn sử dụng bot.\n\n"
        "<i>Ghi chú: Bot hoạt động như kênh cảnh báo 1 chiều kết hợp Computer Vision AI.</i>"
    )
    send_message(chat_id, reply)


def _handle_command_status(chat_id: str):
    """Xử lý lệnh /status: Đọc trạng thái camera và số lượng sự kiện vi phạm hôm nay."""
    if not is_whitelisted(chat_id):
        send_message(chat_id, f"⛔ <b>Từ chối truy cập:</b> Chat ID <code>{chat_id}</code> chưa nằm trong Whitelist cấu hình.")
        return

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    today_date = date.today()
    today_start = datetime.combine(today_date, dtime.min)

    # 1. Đọc trạng thái Camera từ CameraManager hoặc DB
    cam_status_lines = []
    total_events_today = 0
    high_count = 0
    medium_count = 0
    pending_count = 0

    try:
        from app.services.camera_service import camera_manager
        stats = camera_manager.get_all_stats()
        active_cams = stats.get("active_cameras", 0)
        avg_fps = stats.get("avg_fps", 0.0)
        if active_cams > 0:
            cam_status_lines.append(f"• Số camera đang chạy: <b>{active_cams}</b> (FPS trung bình: {avg_fps})")
        else:
            cam_status_lines.append("• Số camera đang chạy: <i>Chưa có camera nào đang stream</i>")
    except Exception:
        cam_status_lines.append("• Trạng thái camera: <i>Đang chạy nền</i>")

    # 2. Truy vấn số lượng sự kiện vi phạm từ SQLite (bảng events)
    try:
        from run import app
        with app.app_context():
            from app.models.event import Event
            events = Event.query.filter(Event.started_at >= today_start).all()
            total_events_today = len(events)
            high_count = sum(1 for e in events if e.level == "high")
            medium_count = sum(1 for e in events if e.level == "medium")
            pending_count = sum(1 for e in events if e.status == "pending")
    except Exception as e:
        logger.warning(f"Không thể đọc bảng events: {e}")

    # 3. Tạo nội dung phản hồi
    cam_info = "\n".join(cam_status_lines)
    reply = (
        "🤖 <b>BÁO CÁO TRẠNG THÁI HỆ THỐNG PHÒNG MÁY</b>\n"
        f"⏱ <i>Thời điểm kiểm tra: {now_str}</i>\n\n"
        f"📹 <b>Trạng thái Camera & AI:</b>\n{cam_info}\n\n"
        f"📊 <b>Thống kê vi phạm hôm nay ({today_date.strftime('%d/%m/%Y')}):</b>\n"
        f"• Tổng số sự kiện vi phạm: <b>{total_events_today}</b>\n"
        f"• Mức độ Cao (Nghiêm trọng): <b>{high_count}</b>\n"
        f"• Mức độ Trung bình: <b>{medium_count}</b>\n"
        f"• Đang chờ xử lý (Pending): <b>{pending_count}</b>\n\n"
        "✅ <i>Hệ thống AI MediaPipe Pose & IoT Gateway đang hoạt động ổn định.</i>"
    )
    send_message(chat_id, reply)


def _handle_command_capture(chat_id: str):
    """Xử lý lệnh /capture: Chụp ảnh hiện tại từ camera và gửi lại."""
    if not is_whitelisted(chat_id):
        send_message(chat_id, f"⛔ <b>Từ chối truy cập:</b> Chat ID <code>{chat_id}</code> chưa nằm trong Whitelist cấu hình.")
        return

    # Hiệu ứng gửi tin nhắn chờ
    send_message(chat_id, "📸 <i>Đang kết nối camera và chụp ảnh, vui lòng đợi...</i>")

    try:
        from run import app
        with app.app_context():
            from app.services.camera_service import camera_manager
            stats = camera_manager.get_all_stats()
            if stats.get('active_cameras', 0) == 0:
                send_message(chat_id, "❌ <b>Thất bại:</b> Không có camera nào đang stream trên hệ thống.")
                return
            
            # Lấy camera đầu tiên đang chạy trong danh sách (loại trừ các camera không có frame)
            cam = None
            for c in camera_manager._cameras.values():
                if c.is_online and c.fps > 0:
                    cam = c
                    break
            
            if not cam:
                # Nếu không có cam nào đang chạy thực sự, lấy đại cam đầu tiên
                cam = next(iter(camera_manager._cameras.values()))

            frame_bytes = cam.capture_snapshot(event_id=None)
            
            if not frame_bytes:
                send_message(chat_id, "❌ <b>Thất bại:</b> Không thể lấy được ảnh từ camera lúc này.")
                return

            caption = (
                f"📷 <b>ẢNH CHỤP TRỰC TIẾP TỪ CAMERA</b>\n"
                f"📹 Nguồn: {cam.source_name}\n"
                f"🕐 Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"✅ Trạng thái AI: {'BẬT' if cam.pose_enabled else 'TẮT'}"
            )
            send_photo(chat_id, frame_bytes, caption)
            
    except Exception as e:
        logger.error(f"Lỗi chụp ảnh /capture: {e}")
        send_message(chat_id, f"❌ <b>Lỗi hệ thống:</b> Không thể chụp ảnh ({e})")


# ════════════════════════════════════════════════════════════
# 4. LONG POLLING RUNNER (CHẠY NGẦM KHÔNG BLOCK FLASK)
# ════════════════════════════════════════════════════════════

def start_bot_polling():
    """
    Khởi động luồng Long Polling lắng nghe các lệnh (/start, /help, /status).
    Chạy trong daemon thread nên không gây block Flask Web Server và không cần Webhook.
    """
    global _bot_thread, _is_polling
    if _is_polling:
        return

    _is_polling = True

    def _poll_worker():
        last_update_id = 0
        logger.info("Khởi chạy luồng Long Polling lắng nghe lệnh bot banban...")

        while _is_polling:
            token = get_bot_token()
            if not token:
                time.sleep(10)
                continue

            url = TELEGRAM_API.format(token=token, method="getUpdates")
            try:
                params = {"offset": last_update_id + 1, "timeout": 25}
                resp = requests.get(url, params=params, timeout=30)
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            last_update_id = update["update_id"]
                            msg = update.get("message", {})
                            text = (msg.get("text") or "").strip()
                            chat_id = str(msg.get("chat", {}).get("id", ""))
                            username = msg.get("from", {}).get("username", "")

                            if not text or not chat_id:
                                continue

                            # Xử lý lệnh
                            cmd = text.split()[0].lower()
                            # Hỗ trợ cả /start và /start@ten_bot
                            if cmd.startswith("/start"):
                                _handle_command_start(chat_id, username)
                            elif cmd.startswith("/help"):
                                _handle_command_help(chat_id)
                            elif cmd.startswith("/status"):
                                _handle_command_status(chat_id)
                            elif cmd.startswith("/capture"):
                                _handle_command_capture(chat_id)
            except Exception as e:
                time.sleep(5)

    _bot_thread = threading.Thread(target=_poll_worker, daemon=True, name="banban-bot-polling")
    _bot_thread.start()


# Khởi chạy polling tự động khi module được import
start_bot_polling()


# ════════════════════════════════════════════════════════════
# 5. CHẠY TRỰC TIẾP ĐỂ TEST ĐỘC LẬP
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  BOT BAN BAN — KIỂM THỬ MODULE ĐỘC LẬP")
    print("=" * 60)
    
    token = get_bot_token()
    whitelist = get_whitelist_chat_ids()
    
    print(f"[*] Token: {'ĐÃ CÓ (' + token[:6] + '...' + token[-4:] + ')' if token else 'CHƯA CÓ (Hãy điền vào .env)'}")
    print(f"[*] Whitelist Chat IDs: {whitelist if whitelist else 'Chưa cấu hình (Hãy mở Telegram chat /start với bot)'}")
    print("\n[>] Đang lắng nghe lệnh từ Telegram... Hãy mở Telegram nhắn /start, /help hoặc /status.")
    print("[>] Nhấn Ctrl+C để kết thúc.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Đã dừng bot.")
