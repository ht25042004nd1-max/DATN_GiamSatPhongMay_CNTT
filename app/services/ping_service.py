# ============================================================
# app/services/ping_service.py — Dịch vụ tự động quét mạng LAN
# Chạy nền (background thread), Ping định kỳ tất cả IP máy tính
# trong CSDL để cập nhật trạng thái Online/Offline tự động.
# ============================================================
import subprocess
import threading
import time
import platform
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Cấu hình ────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 30   # Quét mỗi 30 giây
PING_TIMEOUT_SECONDS  = 2    # Timeout mỗi lần ping
MAX_WORKERS           = 20   # Số thread song song tối đa


def _ping_host(ip: str) -> tuple[bool, int]:
    """
    Ping một địa chỉ IP. Trả về (success: bool, latency_ms: int).
    Hỗ trợ cả Windows và Linux/macOS.
    """
    system = platform.system().lower()
    try:
        if system == 'windows':
            cmd = ['ping', '-n', '1', '-w', str(PING_TIMEOUT_SECONDS * 1000), ip]
        else:
            cmd = ['ping', '-c', '1', '-W', str(PING_TIMEOUT_SECONDS), ip]

        t_start = time.monotonic()
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PING_TIMEOUT_SECONDS + 1
        )
        latency_ms = int((time.monotonic() - t_start) * 1000)

        success = result.returncode == 0
        return success, latency_ms if success else 0
    except Exception:
        return False, 0


class PingService:
    """
    Service chạy nền, định kỳ Ping tất cả máy tính có IP trong DB.
    Khi phát hiện máy chuyển Online→Offline, gửi cảnh báo Telegram.
    """

    def __init__(self, app=None):
        self._app = app
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._prev_status: dict[int, str] = {}   # computer_id → trạng thái cũ

    def init_app(self, app):
        self._app = app

    # ── Vòng lặp chính ───────────────────────────────────────
    def _run(self):
        logger.info("[PingService] Đã khởi động.")
        while not self._stop_event.wait(SCAN_INTERVAL_SECONDS):
            try:
                self._scan_once()
            except Exception as e:
                logger.error(f"[PingService] Lỗi vòng quét: {e}")

    def _scan_once(self):
        """Quét một lần tất cả máy tính có IP."""
        if self._app is None:
            return

        with self._app.app_context():
            from app import db
            from app.models.computer import Computer

            # Chỉ Ping máy có IP, chưa đặt vào bảo trì
            computers = Computer.query.filter(
                Computer.ip_address.isnot(None),
                Computer.ip_address != '',
                Computer.status != 'maintenance'
            ).all()

            if not computers:
                return

            # Ping song song
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_map = {
                    executor.submit(_ping_host, c.ip_address): c
                    for c in computers
                }

                for future in as_completed(future_map):
                    computer = future_map[future]
                    try:
                        success, latency_ms = future.result()
                    except Exception:
                        success, latency_ms = False, 0

                    old_status = self._prev_status.get(computer.id, computer.status)
                    new_status = 'online' if success else 'offline'

                    # Cập nhật DB
                    computer.status = new_status
                    computer.last_ping_ms = latency_ms if success else None
                    if success:
                        computer.last_seen = datetime.utcnow()

                    # Phát hiện chuyển Online → Offline → cảnh báo
                    if old_status == 'online' and new_status == 'offline':
                        self._alert_offline(computer)
                        logger.warning(
                            f"[PingService] 🔴 {computer.name} ({computer.ip_address}) MẤT KẾT NỐI!"
                        )
                    elif old_status == 'offline' and new_status == 'online':
                        logger.info(
                            f"[PingService] 🟢 {computer.name} ({computer.ip_address}) đã kết nối lại ({latency_ms}ms)"
                        )

                    self._prev_status[computer.id] = new_status

            db.session.commit()
            logger.debug(f"[PingService] Quét xong {len(computers)} máy.")

    def _alert_offline(self, computer):
        """Gửi cảnh báo Telegram khi máy mất kết nối đột ngột."""
        try:
            from app.services.telegram_service import send_simple_message
            room_name = computer.room.name if computer.room else "Không rõ"
            msg = (
                f"⚠️ *CẢNH BÁO MẤT KẾT NỐI*\n\n"
                f"🖥️ Máy: *{computer.name}*\n"
                f"🏫 Phòng: {room_name}\n"
                f"🌐 IP: `{computer.ip_address}`\n"
                f"🕐 Thời gian: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}\n\n"
                f"_Máy tính không phản hồi Ping. Kiểm tra ngay!_"
            )
            threading.Thread(
                target=send_simple_message,
                args=(msg,),
                daemon=True
            ).start()
        except Exception as e:
            logger.error(f"[PingService] Không gửi được Telegram: {e}")

    # ── Quản lý vòng đời ────────────────────────────────────
    def start(self):
        """Khởi động background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name='PingServiceThread',
            daemon=True
        )
        self._thread.start()
        logger.info("[PingService] Thread đã được khởi chạy.")

    def stop(self):
        """Dừng background thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[PingService] Đã dừng.")

    def ping_single(self, computer_id: int) -> dict:
        """Ping ngay lập tức một máy cụ thể (dùng cho API on-demand)."""
        if self._app is None:
            return {'error': 'App chưa khởi tạo'}

        with self._app.app_context():
            from app import db
            from app.models.computer import Computer

            computer = Computer.query.get(computer_id)
            if not computer:
                return {'error': 'Không tìm thấy máy'}
            if not computer.ip_address:
                return {'error': 'Máy chưa cấu hình IP'}

            success, latency_ms = _ping_host(computer.ip_address)
            new_status = 'online' if success else 'offline'

            if computer.status != 'maintenance':
                computer.status = new_status
                computer.last_ping_ms = latency_ms if success else None
                if success:
                    computer.last_seen = datetime.utcnow()
                db.session.commit()

            self._prev_status[computer.id] = new_status
            return {
                'success': success,
                'status': new_status,
                'latency_ms': latency_ms,
                'ip_address': computer.ip_address,
                'name': computer.name
            }


# Singleton instance
ping_service = PingService()
