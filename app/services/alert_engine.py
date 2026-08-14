# ============================================================
# app/services/alert_engine.py — Engine xử lý logic cảnh báo (v3.0)
#
# Pipeline mỗi frame:
#   1. Nhận persons dict từ PoseAnalyzer (có wrist_norm, angle_debug)
#   2. Với mỗi person_id: kiểm tra feet_norm VÀ/HOẶC wrist_norm trong ROI
#   3. Nếu tư thế ∈ ALERT_POSES VÀ (duy trì >= ROI duration_threshold HOẶC is_confirmed_event) → tạo Event
#   4. Cooldown 60s per (person_id × roi_id): tránh spam
#   5. Debounce: cho phép gián đoạn ngắn < DEBOUNCE_SECONDS mà không reset bộ đếm
#   6. Đóng event khi người rời ROI hoặc đứng lại
#   7. Ghi JSON structured event log để tính precision/recall
# ============================================================
import time
import json
import threading
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

# ─── Đường dẫn file JSON event log ─────────────────────────
_LOG_DIR  = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'reports')
)
_LOG_PATH = os.path.join(_LOG_DIR, 'event_log.jsonl')   # JSON Lines format


# ─── Phân cấp mức độ tư thế theo đúng Báo cáo Đồ án ─────────
# Báo cáo:
#   - Đứng      : Bình thường - Mức Low
#   - Cúi người : Mức Medium
#   - Ngồi      : Mức High (nếu trong gầm bàn)
#   - Quỳ       : Mức High (Nguy cơ cao gầm case máy tính)
ALERT_POSES = {'Quy', 'Ngoi', 'Cui nguoi'}

POSE_LEVEL = {
    'Quy':       'high',
    'Ngoi':      'high',
    'Cui nguoi': 'medium',
    'Dung':      'low',
}

COOLDOWN_SECONDS   = 60
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


# ─── Dual ROI Boundary Helper ────────────────────────────
def expand_polygon(points: list, scale: float = 1.04) -> list:
    """
    Mở rộng polygon từ 3% đến 5% (scale=1.04) từ tâm polygon để tạo ROI đi ra (Exit ROI).
    """
    if len(points) < 3:
        return points
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    expanded = []
    for x, y in points:
        ex = cx + scale * (x - cx)
        ey = cy + scale * (y - cy)
        expanded.append([ex, ey])
    return expanded


# ─── Tracker cho một cặp (person_id, roi_id) ──────────────
class PersonROITracker:
    """
    Theo dõi trạng thái vi phạm của một người tại một ROI cụ thể.
    Bao gồm debounce, dwell-time và cooldown.
    """
    def __init__(self, roi_id: int, roi_name: str, threshold: int, level: str):
        self.roi_id          = roi_id
        self.roi_name        = roi_name
        self.threshold       = max(1, int(threshold)) if threshold is not None else 5
        self.level           = level or 'medium'
        self.violation_start: Optional[float] = None
        self.current_pose    = ''
        self.cooldown_until  = 0.0
        self.active_event_id: Optional[int] = None
        self.active_session_id: Optional[str] = None
        self.exit_roi_start: Optional[float] = None

        # Debounce state
        self._last_in_roi_time: Optional[float] = None
        self._debounce_active: bool = False

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def reset_hard(self):
        self.violation_start   = None
        self.current_pose      = ''
        self._last_in_roi_time = None
        self._debounce_active  = False
        self.exit_roi_start    = None

    def reset(self):
        self.reset_hard()

    def notify_in_roi(self, pose: str):
        now = time.time()
        self._last_in_roi_time = now
        self._debounce_active  = False
        self.exit_roi_start    = None

        if self.current_pose != pose:
            self.violation_start = now
            self.current_pose    = pose
        elif self.violation_start is None:
            self.violation_start = now

    def notify_out_roi(self) -> bool:
        now = time.time()
        if self._last_in_roi_time is None:
            return False

        elapsed_out = now - self._last_in_roi_time
        if elapsed_out < DEBOUNCE_SECONDS:
            self._debounce_active = True
            return True
        else:
            return False

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
    """

    def __init__(self):
        self._trackers: dict[tuple, PersonROITracker] = {}
        self._lock      = threading.Lock()
        self._rois_cache = []
        self._cache_ts   = 0.0
        self._CACHE_TTL  = 5.0
        self._created_sessions: dict[str, float] = {}

    def _run_in_app_context(self, fn):
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

    def process_frame(self, pose_result: dict, hip_norm=None):
        persons = pose_result.get('persons', {})
        now = time.time()

        if not persons:
            if pose_result.get('is_detected') and hip_norm is not None:
                persons = {
                    0: {
                        'pose':        pose_result.get('pose', ''),
                        'confidence':  pose_result.get('confidence', 0.0),
                        'hip_norm':    hip_norm,
                        'feet_norm':   hip_norm,
                        'is_stooping': pose_result.get('pose') in ALERT_POSES,
                        'bbox':        pose_result.get('person_bbox'),
                        'centroid':    (0, 0),
                    }
                }
            else:
                with self._lock:
                    for tracker in self._trackers.values():
                        if tracker.active_event_id:
                            self._close_event(tracker)
                        tracker.reset_hard()
                return

        rois = self._get_active_rois()
        active_keys = set()

        with self._lock:
            for pid, info in persons.items():
                pose        = info.get('pose', '')
                hip_norm_p  = info.get('hip_norm')
                feet_norm_p = info.get('feet_norm') or hip_norm_p
                wrist_norm_p = info.get('wrist_norm')
                confidence  = info.get('confidence', 0.0)
                angle_debug = info.get('angle_debug', {})

                is_confirmed_event   = info.get('is_confirmed_event', False)
                is_preliminary_alert = info.get('is_preliminary_alert', False)
                session_id           = info.get('session_id', f"sess_{pid}")
                event_ended_reason   = info.get('event_ended_reason')

                if feet_norm_p is None and hip_norm_p is None:
                    continue

                px, py = feet_norm_p if feet_norm_p else hip_norm_p

                for roi in rois:
                    key     = (pid, roi.id)
                    active_keys.add(key)
                    tracker = self._trackers.get(key)
                    if tracker is None:
                        tracker = PersonROITracker(
                            roi.id, roi.name, roi.duration_threshold, roi.level
                        )
                        self._trackers[key] = tracker

                    entry_points = roi.points
                    exit_points  = expand_polygon(roi.points, scale=1.04)

                    in_entry_roi = point_in_polygon(px, py, entry_points)
                    in_exit_roi  = point_in_polygon(px, py, exit_points)

                    if in_entry_roi:
                        in_roi_feet = True
                        tracker.exit_roi_start = None
                    elif not in_exit_roi:
                        if tracker.exit_roi_start is None:
                            tracker.exit_roi_start = now
                        if now - tracker.exit_roi_start >= 0.5:
                            in_roi_feet = False
                        else:
                            in_roi_feet = True
                    else:
                        in_roi_feet = True

                    in_roi_wrist = False
                    if wrist_norm_p:
                        wx, wy = wrist_norm_p
                        in_roi_wrist = point_in_polygon(wx, wy, entry_points)

                    in_roi = in_roi_feet or in_roi_wrist

                    # ── Cảnh báo khi người ở trong ROI và có tư thế cảnh báo hoặc confirmed ──
                    if in_roi and (pose in ALERT_POSES or is_confirmed_event):
                        tracker.notify_in_roi(pose)
                        
                        session_key = f"{roi.id}_{session_id}"
                        last_created = self._created_sessions.get(session_key, 0)
                        
                        # Kích hoạt khi: Duy trì quá số giây ngưỡng ROI (dwell-time) HOẶC máy trạng thái confirmed
                        is_threshold_reached = (tracker.elapsed() >= tracker.threshold) or is_confirmed_event

                        if is_threshold_reached and tracker.active_event_id is None and (now - last_created > 10.0) and not tracker.is_in_cooldown():
                            self._create_event(
                                tracker, roi, pose, confidence, pid,
                                session_id=session_id,
                                angle_debug=angle_debug,
                                in_roi_hip=(feet_norm_p is not None),
                                in_roi_wrist=in_roi_wrist,
                            )
                            self._created_sessions[session_key] = now
                    else:
                        still_debouncing = tracker.notify_out_roi()
                        if not still_debouncing:
                            if tracker.active_event_id is not None:
                                self._close_event(tracker, note=event_ended_reason)
                            tracker.reset_hard()

            # Cleanup tracker của người biến mất
            for key in list(self._trackers.keys()):
                if key not in active_keys:
                    t = self._trackers[key]
                    still_debouncing = t.notify_out_roi()
                    if not still_debouncing:
                        if t.active_event_id is not None:
                            self._close_event(t, note="kết thúc do mất quan sát")
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
        session_id:   str   = None,
        angle_debug:  dict  = None,
        in_roi_hip:   bool  = False,
        in_roi_wrist: bool  = False,
    ):
        def _do_create():
            try:
                from app import db
                from app.models.event import Event

                # Chuẩn hóa mức độ theo đúng Báo cáo Đồ án:
                # - Quỳ      : Mức High
                # - Ngồi     : Mức High (nếu trong gầm bàn)
                # - Cúi người: Mức Medium (hoặc High nếu ROI cấu hình High)
                # - Đứng     : Mức Low
                if pose in ('Quy', 'Ngoi'):
                    level = 'high'
                elif pose == 'Cui nguoi':
                    level = 'medium' if roi.level != 'high' else 'high'
                else:
                    level = POSE_LEVEL.get(pose, roi.level or 'medium')

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
                    note             = f"Session: {session_id}" if session_id else None
                )
                db.session.add(ev)
                db.session.commit()

                tracker.active_event_id   = ev.id
                tracker.active_session_id = session_id
                tracker.cooldown_until    = time.time() + COOLDOWN_SECONDS
                tracker.violation_start   = None

                print(f"[Alert] Event #{ev.id} | Session: {session_id} | ROI: {roi.name} | Person P{person_id} | Pose: {pose} | Level: {level.upper()}")

                # ── Ghi JSON event log ───────────────────────────
                self._write_json_log({
                    "event_id":      ev.id,
                    "session_id":    session_id,
                    "timestamp":     datetime.utcnow().isoformat() + 'Z',
                    "track_id":      person_id,
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
    def _close_event(self, tracker: PersonROITracker, note: str = None):
        def _do_close():
            try:
                from app import db
                from app.models.event import Event
                ev = Event.query.get(tracker.active_event_id)
                if ev and ev.ended_at is None:
                    ev.ended_at = datetime.utcnow()
                    if note:
                        ev.note = f"{ev.note} | {note}" if ev.note else note
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
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[Alert] Loi ghi JSON log: {e}")

    def get_log_path(self) -> str:
        return _LOG_PATH


# Singleton toàn cục
alert_engine = AlertEngine()
