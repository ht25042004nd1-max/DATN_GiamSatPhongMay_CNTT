# ============================================================
# app/services/alert_engine.py — Engine xử lý logic cảnh báo (v3.0)
#
# Nâng cấp v3.0: tương thích PoseAnalyzer v3.0 (YOLOv8-Pose + ByteTrack)
# Pipeline mỗi frame:
#   1. Nhận persons dict từ PoseAnalyzer (có wrist_norm, angle_debug)
#   2. Với mỗi person_id: kiểm tra hip_norm VÀ/HOẶC wrist_norm trong ROI
#   3. Nếu tư thế ∈ ALERT_POSES VÀ is_stooping=True VÀ trong ROI → tạo Event
#   4. Cooldown 60s per (person_id × roi_id): tránh spam
#   5. Debounce: cho phép gián đoạn ngắn < DEBOUNCE_SECONDS mà không reset bộ đếm
#   6. Đóng event khi người rời ROI hoặc đứng lại
#   7. Ghi JSON structured event log để tính precision/recall (Nhiệm vụ 4)
# ============================================================
import time
import json
import threading
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

# ─── Đường dẫn file JSON event log (Nhiệm vụ 4) ──────────
_LOG_DIR  = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'reports')
)
_LOG_PATH = os.path.join(_LOG_DIR, 'event_log.jsonl')   # JSON Lines format


# ─── Tư thế kích hoạt cảnh báo ────────────────────────────
ALERT_POSES = {'Quy', 'Ngoi', 'Cui nguoi'}

POSE_LEVEL = {
    'Quy':       'high',
    'Ngoi':      'high',
    'Cui nguoi': 'medium',
    'Dung':      'low',
}

COOLDOWN_SECONDS   = 60

# ─── Debounce ROI (Nhiệm vụ 3) ────────────────────────────
# Cho phép gián đoạn ngắn < DEBOUNCE_SECONDS mà không reset bộ đếm dwell-time
# Ví dụ: occlusion thoáng qua, tracker nhập nháy 1 frame → không mất dấu
DEBOUNCE_SECONDS   = 2.0


# ─── Point-In-Polygon (Ray Casting) ───────────────────────
def point_in_polygon(px: float, py: float, polygon: list) -> bool:
    """
    Kiểm tra điểm (px, py) có nằm trong polygon không.
    Dùng thuật toán Ray Casting.
    px, py: tọa độ chuẩn hóa 0.0–1.0
    polygon: [[x1,y1],[x2,y2],...] chuẩn hóa 0.0–1.0
    """
    if len(polygon) < 3:
        return False
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi + 1e-10) + xi):
            inside = not inside
        j = i
    return inside


# ─── Tracker cho một cặp (person_id, roi_id) ──────────────
class PersonROITracker:
    """
    Theo dõi trạng thái vi phạm của một người tại một ROI cụ thể.

    v3.0: Thêm debounce — cho phép gián đoạn ngắn < DEBOUNCE_SECONDS
    (occlusion thoáng qua, track nhập nháy) mà không reset bộ đếm về 0.
    Giúp dwell-time counter không bị phá vỡ bởi noise ngắn hạn.
    """
    def __init__(self, roi_id: int, roi_name: str, threshold: int, level: str):
        self.roi_id          = roi_id
        self.roi_name        = roi_name
        self.threshold       = threshold
        self.level           = level
        self.violation_start: Optional[float] = None
        self.current_pose    = ''
        self.cooldown_until  = 0.0
        self.active_event_id: Optional[int] = None
        # Debounce state (Nhiệm vụ 3)
        self._last_in_roi_time: Optional[float] = None  # Lần cuối trong ROI
        self._debounce_active: bool = False              # Đang trong window debounce

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def reset_hard(self):
        """Reset hoàn toàn — người đã rời ROI quá lâu (> DEBOUNCE_SECONDS)."""
        self.violation_start   = None
        self.current_pose      = ''
        self._last_in_roi_time = None
        self._debounce_active  = False

    def reset(self):
        """Alias tương thích ngược."""
        self.reset_hard()

    def notify_in_roi(self, pose: str):
        """
        Gọi mỗi frame khi người CÒN trong ROI.
        Cập nhật bộ đếm dwell-time.
        """
        now = time.time()
        self._last_in_roi_time = now
        self._debounce_active  = False

        if self.current_pose != pose:
            # Tư thế thay đổi → reset thời điểm bắt đầu
            self.violation_start = now
            self.current_pose    = pose
        elif self.violation_start is None:
            self.violation_start = now

    def notify_out_roi(self) -> bool:
        """
        Gọi mỗi frame khi người KHÔNG trong ROI.
        Trả về True nếu vẫn đang trong debounce window (bộ đếm chưa reset).
        Trả về False nếu đã hết debounce → cần reset_hard().
        """
        now = time.time()
        if self._last_in_roi_time is None:
            return False  # Chưa từng vào ROI

        elapsed_out = now - self._last_in_roi_time
        if elapsed_out < DEBOUNCE_SECONDS:
            # Còn trong debounce window → không reset bộ đếm
            self._debounce_active = True
            return True
        else:
            # Hết debounce → reset hoàn toàn
            return False

    def start_tracking(self, pose: str):
        """Legacy compat — sử dụng notify_in_roi() thay thế trong v3.0."""
        if self.current_pose != pose:
            self.violation_start = time.time()
            self.current_pose    = pose
        elif self.violation_start is None:
            self.violation_start = time.time()

    def elapsed(self) -> float:
        if self.violation_start is None:
            return 0.0
        return time.time() - self.violation_start


# ─── Alert Engine ──────────────────────────────────────────
class AlertEngine:
    """
    Engine trung tâm xử lý cảnh báo đa người.
    Được gọi từ CameraService sau mỗi frame AI xử lý xong.
    """

    def __init__(self):
        # (person_id, roi_id) → PersonROITracker
        self._trackers: dict[tuple, PersonROITracker] = {}
        self._lock      = threading.Lock()
        self._rois_cache = []
        self._cache_ts   = 0.0
        self._CACHE_TTL  = 5.0

    def _run_in_app_context(self, fn):
        """Đảm bảo hàm thực thi bên trong Flask Application Context."""
        try:
            from flask import has_app_context, current_app
            if has_app_context():
                return fn()
            elif current_app:
                with current_app.app_context():
                    return fn()
        except Exception:
            pass
        return fn()

    # ── Load ROI có cache ──────────────────────────────────
    def _get_active_rois(self):
        now = time.time()
        if now - self._cache_ts > self._CACHE_TTL:
            def _do_fetch():
                from app.models.roi import ROI
                return ROI.query.filter_by(is_active=True).all()
            
            res = self._run_in_app_context(_do_fetch)
            if res is not None:
                self._rois_cache = res
                self._cache_ts = now
        return self._rois_cache

    def invalidate_cache(self):
        self._cache_ts = 0.0

    # ── Xử lý frame (hỗ trợ cả dict nhiều người và tương thích ngược) ──
    def process_frame(self, pose_result: dict, hip_norm=None):
        """
        Hỗ trợ 2 chế độ gọi:
        1. Mới (v2.0): pose_result chứa key 'persons' → dict đa người
        2. Cũ (v1.0): pose_result + hip_norm riêng lẻ (backward compatible)
        """
        persons = pose_result.get('persons', {})

        if not persons:
            # Fallback tương thích ngược: tạo dict giả từ single person
            if pose_result.get('is_detected') and hip_norm is not None:
                persons = {
                    0: {
                        'pose':        pose_result.get('pose', ''),
                        'confidence':  pose_result.get('confidence', 0.0),
                        'hip_norm':    hip_norm,
                        'is_stooping': pose_result.get('pose') in ALERT_POSES,
                        'bbox':        pose_result.get('person_bbox'),
                        'centroid':    (0, 0),
                    }
                }
            else:
                # Không có ai → reset tất cả tracker
                with self._lock:
                    for tracker in self._trackers.values():
                        tracker.reset()
                return

        rois = self._get_active_rois()
        active_keys = set()

        with self._lock:
            for pid, info in persons.items():
                pose        = info.get('pose', '')
                hip_norm_p  = info.get('hip_norm')
                wrist_norm_p = info.get('wrist_norm')   # v3.0: thêm wrist check
                is_stooping = info.get('is_stooping', False)
                confidence  = info.get('confidence', 0.0)
                angle_debug = info.get('angle_debug', {})

                if hip_norm_p is None and wrist_norm_p is None:
                    continue

                # Tọa độ hip để kiểm tra người trong ROI
                px, py = hip_norm_p if hip_norm_p else (0.0, 0.0)

                for roi in rois:
                    key     = (pid, roi.id)
                    active_keys.add(key)
                    tracker = self._trackers.get(key)
                    if tracker is None:
                        tracker = PersonROITracker(
                            roi.id, roi.name, roi.duration_threshold, roi.level
                        )
                        self._trackers[key] = tracker

                    # Kiểm tra hip trong ROI (như cũ)
                    in_roi_hip = point_in_polygon(px, py, roi.points) if hip_norm_p else False

                    # Kiểm tra thêm WRIST trong ROI (Nhiệm vụ 3 — phát hiện tay gần Case)
                    in_roi_wrist = False
                    if wrist_norm_p:
                        wx, wy = wrist_norm_p
                        in_roi_wrist = point_in_polygon(wx, wy, roi.points)

                    # Người được coi là "trong ROI" nếu hip HOẶC wrist trong ROI
                    in_roi = in_roi_hip or in_roi_wrist

                    # Điều kiện vi phạm: tư thế nguy hiểm + trong ROI
                    if in_roi and pose in ALERT_POSES:
                        if tracker.is_in_cooldown():
                            continue
                        # v3.0: dùng notify_in_roi() thay start_tracking()
                        tracker.notify_in_roi(pose)
                        if tracker.elapsed() >= roi.duration_threshold:
                            self._create_event(
                                tracker, roi, pose, confidence, pid,
                                angle_debug=angle_debug,
                                in_roi_hip=in_roi_hip,
                                in_roi_wrist=in_roi_wrist,
                            )
                    else:
                        # Người ngoài ROI: kiểm tra debounce trước khi reset
                        still_debouncing = tracker.notify_out_roi()
                        if not still_debouncing:
                            # Hết debounce hoàn toàn → đóng event và reset
                            if tracker.active_event_id is not None:
                                self._close_event(tracker)
                            tracker.reset_hard()
                        # Nếu vẫn đang debounce → giữ nguyên bộ đếm

            # Cleanup: reset và xóa tracker của người đã biến mất khỏi khung hình
            for key in list(self._trackers.keys()):
                if key not in active_keys:
                    t = self._trackers[key]
                    # Kiểm tra debounce trước khi xóa hẳn
                    still_debouncing = t.notify_out_roi()
                    if not still_debouncing:
                        if t.active_event_id is not None:
                            self._close_event(t)
                        t.reset_hard()
                        del self._trackers[key]

    # ── Tạo Event ─────────────────────────────────────────
    def _create_event(
        self,
        tracker:      PersonROITracker,
        roi,
        pose:         str,
        confidence:   float = 0.0,
        person_id:    int   = 0,
        angle_debug:  dict  = None,
        in_roi_hip:   bool  = False,
        in_roi_wrist: bool  = False,
    ):
        def _do_create():
            try:
                from app import db
                from app.models.event import Event

                level = POSE_LEVEL.get(pose, roi.level)
                cam_id = getattr(roi, 'camera_id', None) or 1
                room_id = None
                if cam_id:
                    try:
                        from app.models.camera import Camera
                        cam_obj = Camera.query.get(cam_id)
                        if cam_obj:
                            room_id = cam_obj.room_id
                    except Exception:
                        pass

                ev = Event(
                    roi_id           = roi.id,
                    roi_name         = roi.name,
                    camera_id        = cam_id,
                    room_id          = room_id,
                    pose             = pose,
                    level            = level,
                    person_count     = 1,
                    started_at       = datetime.utcnow(),
                    status           = 'pending',
                    confidence_score = confidence,
                )
                db.session.add(ev)
                db.session.commit()

                tracker.active_event_id = ev.id
                tracker.cooldown_until  = time.time() + COOLDOWN_SECONDS
                tracker.violation_start = None

                print(f"[Alert] Event #{ev.id} | ROI: {roi.name} | Person P{person_id} | Pose: {pose}")

                # ── Ghi JSON event log (Nhiệm vụ 4) ─────────────
                self._write_json_log({
                    "event_id":      ev.id,
                    "timestamp":     datetime.utcnow().isoformat() + 'Z',
                    "track_id":      person_id,   # Track ID tạm thời, không phải danh tính
                    "camera_id":     cam_id,
                    "room_id":       room_id,
                    "roi_id":        roi.id,
                    "roi_name":      roi.name,
                    "pose":          pose,
                    "level":         level,
                    "confidence":    round(confidence, 2),
                    "dwell_elapsed": round(tracker.elapsed(), 1),
                    "in_roi_hip":    in_roi_hip,
                    "in_roi_wrist":  in_roi_wrist,
                    "angle_debug":   angle_debug or {},
                })

                # Đọc chế độ gửi Telegram
                try:
                    from app.models.setting import SystemSetting
                    send_mode = SystemSetting.get('telegram_send_mode', 'mandatory')
                except Exception:
                    send_mode = 'mandatory'

                # Chụp ảnh + Telegram
                try:
                    from app.services.telegram_service import send_alert
                    from app.services.camera_service import camera_manager
                    cam_service = camera_manager.get_camera(cam_id)
                    frame_bytes = cam_service.capture_snapshot(event_id=ev.id) if cam_service else None
                    send_alert(ev, frame_bytes=frame_bytes, send_mode=send_mode)
                except Exception as tg_err:
                    print(f"[Alert] Telegram: {tg_err}")

                # Kích hoạt IoT
                try:
                    from app.services.esp32_service import trigger_alert_hardware
                    trigger_alert_hardware(ev)
                except Exception as iot_err:
                    print(f"[Alert] IoT: {iot_err}")

            except Exception as e:
                print(f"[Alert] Lỗi tạo event: {e}")

        self._run_in_app_context(_do_create)

    # ── Đóng Event ────────────────────────────────────────
    def _close_event(self, tracker: PersonROITracker):
        def _do_close():
            try:
                from app import db
                from app.models.event import Event
                ev = Event.query.get(tracker.active_event_id)
                if ev and ev.ended_at is None:
                    ev.ended_at = datetime.utcnow()
                    db.session.commit()
                tracker.active_event_id = None
                try:
                    from app.services.esp32_service import send_iot_command
                    send_iot_command('relay', 0)
                except Exception:
                    pass
            except Exception as e:
                print(f"[Alert] Lỗi đóng event: {e}")

        self._run_in_app_context(_do_close)

    def get_recent_events_count(self) -> int:
        try:
            from app.models.event import Event
            return Event.query.filter_by(status='pending').count()
        except Exception:
            return 0

    # ── Ghi JSON event log ────────────────────────────────
    def _write_json_log(self, record: dict):
        """
        Ghi một bản ghi event vào file JSON Lines (reports/event_log.jsonl).
        Mỗi dòng là một JSON object độc lập → dễ đọc bằng pandas / jq.
        Dữ liệu này dùng để tính precision/recall trên video test có gán nhãn.
        Không lưu danh tính cá nhân — chỉ track_id tạm thời theo phiên.
        """
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[Alert] Loi ghi JSON log: {e}")

    def get_log_path(self) -> str:
        """Trả về đường dẫn file JSON event log."""
        return _LOG_PATH


# Singleton toàn cục
alert_engine = AlertEngine()
