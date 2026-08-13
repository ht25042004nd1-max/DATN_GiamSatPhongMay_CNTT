# ============================================================
# app/services/alert_engine.py — Engine xử lý logic cảnh báo (v2.0)
#
# Nâng cấp: xử lý dict nhiều người {person_id: info} từ PoseAnalyzer v2.
# Pipeline mỗi frame:
#   1. Nhận persons dict từ PoseAnalyzer
#   2. Với mỗi person_id: kiểm tra hip_norm có trong ROI nào không
#   3. Nếu tư thế ∈ ALERT_POSES VÀ is_stooping=True VÀ trong ROI → tạo Event
#   4. Cooldown 60s per (person_id × roi_id): tránh spam
#   5. Đóng event khi người rời ROI hoặc đứng lại
# ============================================================
import time
import threading
from datetime import datetime
from typing import Optional


# ─── Tư thế kích hoạt cảnh báo ────────────────────────────
ALERT_POSES = {'Quy', 'Ngoi', 'Cui nguoi'}

POSE_LEVEL = {
    'Quy':       'high',
    'Ngoi':      'high',
    'Cui nguoi': 'medium',
    'Dung':      'low',
}

COOLDOWN_SECONDS = 60


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

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def reset(self):
        self.violation_start = None
        self.current_pose    = ''

    def start_tracking(self, pose: str):
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
                is_stooping = info.get('is_stooping', False)
                confidence  = info.get('confidence', 0.0)

                if hip_norm_p is None:
                    continue

                px, py = hip_norm_p

                for roi in rois:
                    key     = (pid, roi.id)
                    active_keys.add(key)
                    tracker = self._trackers.get(key)
                    if tracker is None:
                        tracker = PersonROITracker(
                            roi.id, roi.name, roi.duration_threshold, roi.level
                        )
                        self._trackers[key] = tracker

                    in_roi = point_in_polygon(px, py, roi.points)

                    # Điều kiện vi phạm:
                    # tư thế nguy hiểm + trong ROI
                    if in_roi and pose in ALERT_POSES:
                        if tracker.is_in_cooldown():
                            continue
                        tracker.start_tracking(pose)
                        if tracker.elapsed() >= roi.duration_threshold:
                            self._create_event(tracker, roi, pose, confidence, pid)
                    else:
                        if tracker.active_event_id is not None:
                            self._close_event(tracker)
                        tracker.reset()

            # Cleanup: reset và xóa tracker của người đã biến mất khỏi khung hình
            for key in list(self._trackers.keys()):
                if key not in active_keys:
                    t = self._trackers[key]
                    if t.active_event_id is not None:
                        self._close_event(t)
                    t.reset()
                    del self._trackers[key]

    # ── Tạo Event ─────────────────────────────────────────
    def _create_event(self, tracker: PersonROITracker, roi, pose: str,
                      confidence: float = 0.0, person_id: int = 0):
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

                print(f"[Alert] Event #{ev.id} | ROI: {roi.name} | Person P{person_id+1} | Pose: {pose}")

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


# Singleton toàn cục
alert_engine = AlertEngine()
