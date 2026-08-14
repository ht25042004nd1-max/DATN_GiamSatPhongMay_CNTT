# ============================================================
# app/services/pose_analyzer.py — Phân tích tư thế đa người (v3.0)
#
# Pipeline (v3.0):
#   YOLOv8m-Pose (17 kpts COCO) + ByteTrack → classify_posture() →
#   TemporalBuffer → kết quả dict per track_id
#
# Thay đổi so với v2.0 (MediaPipe):
#   - Chuyển từ MediaPipe 33 kpts → YOLOv8-Pose COCO 17 kpts
#   - Xóa CentroidTracker thủ công → dùng ByteTrack tích hợp Ultralytics
#   - Thêm filter_low_confidence_persons (Nhiệm vụ 1b)
#   - Thêm K-frame confirmation: track_id chỉ tính là "người hợp lệ"
#     sau khi xuất hiện liên tục >= K_FRAME_CONFIRM frame (Nhiệm vụ 1c)
#   - Thêm classify_posture() với temporal smoothing (Nhiệm vụ 2)
#   - Thêm angle_debug và wrist_norm trong output mỗi person
#   - MediaPipe giữ làm fallback nếu YOLOv8 không load được
#
# Model: models/yolov8m-pose.pt (tải bằng download_model.py)
# Fallback: models/pose_landmarker_lite.task (MediaPipe)
# ============================================================
import numpy as np
import cv2
import os
import time
import threading
from collections import deque, OrderedDict
from typing import Optional

# ─── Import module phân loại tư thế (Nhiệm vụ 2) ──────────
from app.services.posture_classifier import (
    classify_posture,
    filter_low_confidence_persons,
    AngleHistoryBuffer,
    KPT_LEFT_HIP, KPT_RIGHT_HIP,
    KPT_LEFT_SHOULDER, KPT_RIGHT_SHOULDER,
    KPT_LEFT_WRIST, KPT_RIGHT_WRIST,
    KPT_LEFT_KNEE, KPT_RIGHT_KNEE,
    KPT_LEFT_ANKLE, KPT_RIGHT_ANKLE,
)

# ─── Đường dẫn model ───────────────────────────────────────
_MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'models')
)
_YOLO_MODEL_PATH      = os.path.join(_MODEL_DIR, 'yolov8m-pose.pt')
_MEDIAPIPE_MODEL_PATH = os.path.join(_MODEL_DIR, 'pose_landmarker_lite.task')

# ─── Cấu hình YOLOv8 Predict / Track ──────────────────────
YOLO_CONF         = 0.45    # Ngưỡng phát hiện người (tối thiểu 0.45)
YOLO_IOU          = 0.45    # NMS IoU
YOLO_AGNOSTIC_NMS = True    # NMS không phân biệt lớp (chỉ detect "person")
YOLO_MAX_DET      = 10      # Giới hạn hợp lý theo sức chứa phòng máy

# ─── Cấu hình K-frame Confirmation (theo dõi >= 0.5s ở 15 FPS) ─
K_FRAME_CONFIRM   = 8       # 8 frame liên tục (~0.5s ở 15 FPS) mới xác nhận người hợp lệ

# ─── Cấu hình Keypoint Filter ─────────────────────────────
MIN_KPTS_VALID    = 6       # Tối thiểu 6/17 keypoint đủ tin cậy (>= 0.40)
KPT_CONF_THRESHOLD = 0.40   # Ngưỡng tin cậy từng keypoint

# ─── Cấu hình TemporalBuffer & Dwell-time ─────────────────
BUFFER_SECONDS          = 5.0   # Giữ lịch sử 5 giây gần nhất
STOOP_THRESHOLD_SEC     = 3.0   # Hạ người liên tục >= 3s → hành vi bất thường
HIGH_ALERT_THRESHOLD_SEC = 5.0  # Mức cảnh báo cao >= 5s
STOOP_DROP_RATIO        = 0.05  # Tâm hông phải hạ >= 5% chiều cao frame
UNSEEN_TOLERANCE_SEC    = 0.5   # Mất dấu < 0.5s duy trì Track ID tránh tạo đối tượng mới

# ─── Màu sắc (BGR — OpenCV) ────────────────────────────────
C_LANDMARK   = (0, 212, 255)    # Xanh lam-vàng
C_CONNECT    = (100, 180, 255)  # Xanh nhạt
C_NORMAL_BOX = (50, 200, 50)    # Xanh lá — bình thường
C_ALERT_BOX  = (0, 0, 220)      # Đỏ — vi phạm
C_ID_TEXT    = (255, 255, 255)  # Trắng
C_UNCONFIRMED = (80, 80, 80)    # Xám — chưa đủ K frame

# ─── Skeleton connections COCO 17 điểm ────────────────────
COCO_CONNECTIONS = [
    (5, 6),   # vai trái — vai phải
    (5, 7),   # vai trái — khuỷu trái
    (7, 9),   # khuỷu trái — cổ tay trái
    (6, 8),   # vai phải — khuỷu phải
    (8, 10),  # khuỷu phải — cổ tay phải
    (5, 11),  # vai trái — hông trái
    (6, 12),  # vai phải — hông phải
    (11, 12), # hông trái — hông phải
    (11, 13), # hông trái — gối trái
    (13, 15), # gối trái — mắt cá trái
    (12, 14), # hông phải — gối phải
    (14, 16), # gối phải — mắt cá phải
]
MIN_KPT_VIS = 0.3   # Ngưỡng visibility để vẽ keypoint / đường nối


# ════════════════════════════════════════════════════════════
# CLASS: TemporalBuffer — Theo dõi dwell-time theo trục Y
# ════════════════════════════════════════════════════════════
class TemporalBuffer:
    """
    Lưu lịch sử tọa độ tâm Y (chuẩn hóa) của một người trong BUFFER_SECONDS giây.
    Phát hiện "cúi người liên tục" bằng phân tích xu hướng thời gian.

    Logic: Nếu Y hiện tại cao hơn baseline Y đầu buffer thêm STOOP_DROP_RATIO
    (= người đang thấp hơn lúc ban đầu) VÀ duy trì >= STOOP_THRESHOLD_SEC giây.
    """

    def __init__(self):
        self.buffer: deque = deque()       # (timestamp, y_center_normalized)
        self.stoop_start: Optional[float] = None

    def update(self, y_norm: float):
        """Thêm điểm dữ liệu mới và loại bỏ điểm quá cũ."""
        now = time.monotonic()
        self.buffer.append((now, y_norm))
        cutoff = now - BUFFER_SECONDS
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    def is_stooping(self, threshold_sec: float = STOOP_THRESHOLD_SEC) -> bool:
        """Trả về True nếu người đang ở tư thế thấp liên tục >= threshold_sec giây."""
        if len(self.buffer) < 3:
            return False
        now = time.monotonic()

        # Baseline: trung bình Y trong 1 giây đầu buffer
        baseline_pts = [y for t, y in self.buffer if t <= self.buffer[0][0] + 1.0]
        if not baseline_pts:
            return False
        baseline_y = float(np.mean(baseline_pts))

        # Hiện tại: trung bình Y trong 0.5s gần nhất
        cutoff_recent = now - 0.5
        recent_pts = [y for t, y in self.buffer if t >= cutoff_recent]
        if not recent_pts:
            return False
        current_y = float(np.mean(recent_pts))

        is_low = current_y > baseline_y + STOOP_DROP_RATIO

        if is_low:
            if self.stoop_start is None:
                self.stoop_start = now
            return (now - self.stoop_start) >= threshold_sec
        else:
            self.stoop_start = None
            return False

    def reset(self):
        self.buffer.clear()
        self.stoop_start = None


# ════════════════════════════════════════════════════════════
# CLASS: PersonTrackState — Máy trạng thái hành vi 6 cấp cho từng người
# ════════════════════════════════════════════════════════════
class PersonTrackState:
    """
    Quản lý máy trạng thái hành vi cho từng người (track_id).
    Các trạng thái:
      - UNCONFIRMED : chưa đủ K frame (0.5s) hoặc vị trí chưa ổn định
      - NORMAL      : bình thường (thiết lập base_pose sau 15 frame / 1.5s và đứng ổn định >= 0.8s)
      - LOWERING    : đang hạ người (v_hip > 0.15 body-height/s hoặc hông hạ >= 8%)
      - CANDIDATE   : hành vi ứng viên (hông hạ >= 15% + bằng chứng hỗ trợ)
      - CONFIRMED   : hành vi bất thường đã xác nhận (cửa sổ dwell-time >= 3.0s liên tục)
      - RECOVERING  : đang phục hồi (hông hạ < 12%, cần 3s liên tục < 8% để về NORMAL)
      - LOST        : mất theo dõi (> 1.5s)
    """
    def __init__(self, track_id: int):
        self.track_id = track_id
        self.state = "UNCONFIRMED"
        self.first_seen = time.time()
        self.last_seen = time.time()
        self.unseen_duration = 0.0

        # Base pose profile
        from app.services.posture_classifier import BasePoseProfile
        self.base_pose = BasePoseProfile()
        self.base_pose_samples = []
        self.normal_start_time: Optional[float] = None
        self.standing_frames_count = 0

        # Velocity tracking
        self.last_hip_y: Optional[float] = None
        self.last_hip_time: Optional[float] = None
        self.current_v_hip: float = 0.0

        # History buffer (lưu tối đa 150 frame ~ 10 giây ở 15 FPS)
        # Mỗi item: (timestamp, is_valid, is_target_posture, hip_drop_ratio, label, conf)
        self.history = deque(maxlen=150)

        # State timers & tracking
        self.lowering_start_time: Optional[float] = None
        self.candidate_start_time: Optional[float] = None
        self.recovering_start_time: Optional[float] = None

        # Event session identity
        self.session_id = f"sess_{track_id}_{int(time.time() * 1000)}"
        self.is_confirmed_event = False
        self.is_high_alert = False
        self.is_preliminary_alert = False
        self.max_hip_drop = 0.0
        self.max_confidence = 0.0
        self.event_ended_reason = None
        self.confirmed_at: Optional[float] = None

    def compute_hip_velocity(self, kpts, confs, now: float) -> float:
        """
        Tính vận tốc chuyển động hạ hông theo phương dọc (Y), chuẩn hóa theo body_height / giây.
        Giá trị dương > 0: chuyển động đi xuống (hạ người).
        Giá trị âm < 0: chuyển động đi lên.
        """
        if kpts is None or confs is None:
            return 0.0
        lhp_c = float(confs[KPT_LEFT_HIP])
        rhp_c = float(confs[KPT_RIGHT_HIP])
        if lhp_c < 0.60 and rhp_c < 0.60:
            return 0.0

        lhp = kpts[KPT_LEFT_HIP]
        rhp = kpts[KPT_RIGHT_HIP]
        curr_y = float((lhp[1] * lhp_c + rhp[1] * rhp_c) / (lhp_c + rhp_c + 1e-7))

        if self.last_hip_y is None or self.last_hip_time is None:
            self.last_hip_y = curr_y
            self.last_hip_time = now
            return 0.0

        dt = now - self.last_hip_time
        if dt < 0.01:
            return self.current_v_hip

        ref_h = self.base_pose.body_height if (self.base_pose and self.base_pose.is_established) else 300.0
        dy = curr_y - self.last_hip_y
        raw_v = float((dy / max(ref_h, 10.0)) / dt)

        # Smooth EMA
        self.current_v_hip = float(0.6 * self.current_v_hip + 0.4 * raw_v)
        self.last_hip_y = curr_y
        self.last_hip_time = now
        return self.current_v_hip

    def update(self, frame_res: dict, now: float):
        """Cập nhật máy trạng thái theo từng frame xử lý."""
        is_valid = frame_res.get('is_valid_frame', False)

        if is_valid:
            self.unseen_duration = 0.0
            self.last_seen = now
            label = frame_res.get('label', 'Dung')
            conf = frame_res.get('confidence', 0.0)
            hip_drop = frame_res.get('hip_drop_ratio', 0.0)
            has_support = frame_res.get('has_supporting_evidence', False)
            v_hip = frame_res.get('v_hip', 0.0)

            is_target = label in ('Cui nguoi', 'Quy', 'Ngoi') or hip_drop >= 0.15
            self.history.append((now, True, is_target, hip_drop, label, conf))

            # Cập nhật peak metrics
            if hip_drop > self.max_hip_drop:
                self.max_hip_drop = hip_drop
            if conf > self.max_confidence:
                self.max_confidence = conf

            # ── 1. UNCONFIRMED → NORMAL (xác nhận người hợp lệ trong 0.5s) ──
            if self.state == "UNCONFIRMED":
                elapsed = now - self.first_seen
                valid_cnt = sum(1 for item in self.history if item[1])
                total_cnt = len(self.history)
                # Xuất hiện hợp lệ >= 70% trong >= 0.5s (~7-8 frame ở 15 FPS)
                if elapsed >= 0.5 and total_cnt > 0 and (valid_cnt / total_cnt) >= 0.70:
                    self.state = "NORMAL"
                    self.normal_start_time = now

            # ── 2. Thiết lập tư thế cơ sở BasePose trong 1.5s đầu ở NORMAL ──
            if self.state == "NORMAL" and not self.base_pose.is_established:
                if self.normal_start_time is None:
                    self.normal_start_time = now
                if 'frame_metrics' in frame_res:
                    self.base_pose_samples.append(frame_res['frame_metrics'])
                    if label == "Dung" or frame_res.get('frame_metrics', {}).get('torso_angle', 180.0) >= 140.0:
                        self.standing_frames_count += 1
                
                # Đạt 1.5s VÀ >= 15 frame VÀ đứng ổn định >= 0.8s (~12 frame)
                if (now - self.normal_start_time >= 1.5 and len(self.base_pose_samples) >= 15 and self.standing_frames_count >= 10):
                    self.base_pose.update_from_samples(self.base_pose_samples, standing_duration=(self.standing_frames_count * 0.066))

            # ── 3. NORMAL → LOWERING (v_hip > 0.15 body-height/s hoặc hông hạ >= 8%) ──
            if self.state == "NORMAL" and (v_hip > 0.15 or hip_drop >= 0.08):
                if self.lowering_start_time is None:
                    self.lowering_start_time = now
                elif now - self.lowering_start_time >= 0.2:
                    self.state = "LOWERING"

            # ── 4. LOWERING / NORMAL → CANDIDATE (hông hạ >= 15% + bằng chứng hỗ trợ) ──
            if self.state in ("NORMAL", "LOWERING") and hip_drop >= 0.15 and has_support:
                self.state = "CANDIDATE"
                if self.candidate_start_time is None:
                    self.candidate_start_time = now

            # ── 5. CẢNH BÁO SƠ BỘ (1s ở tư thế thấp, >= 70% thời gian) ──
            if self.state == "CANDIDATE":
                valid_items = [item for item in self.history if item[1] and item[0] >= now - 3.0]
                if valid_items:
                    target_time = sum(1 for item in valid_items if item[2])
                    target_ratio = target_time / len(valid_items)
                    cand_dur = now - (self.candidate_start_time or now)
                    if cand_dur >= 1.0 and target_ratio >= 0.70:
                        self.is_preliminary_alert = True

            # ── 6. CANDIDATE → CONFIRMED (Dwell-time >= 3.0s liên tục) ──
            if self.state == "CANDIDATE":
                cand_dur = now - (self.candidate_start_time or now)
                window_items = [item for item in self.history if item[0] >= now - STOOP_THRESHOLD_SEC]
                valid_items = [item for item in window_items if item[1]]

                if len(valid_items) > 0 and cand_dur >= STOOP_THRESHOLD_SEC:
                    target_count = sum(1 for item in valid_items if item[2])
                    target_ratio = target_count / len(valid_items)
                    avg_conf = float(np.mean([item[5] for item in valid_items]))

                    # Điều kiện xác nhận: Duy trì >= 3.0s, target posture >= 75%, avg_conf >= 70%
                    if target_ratio >= 0.75 and avg_conf >= 65.0:
                        self.state = "CONFIRMED"
                        self.is_confirmed_event = True
                        self.confirmed_at = now

            # ── 7. MỨC CẢNH BÁO CAO (Dwell-time >= 5.0s liên tục) ──
            if self.state == "CONFIRMED":
                total_low_dur = now - (self.candidate_start_time or now)
                if total_low_dur >= HIGH_ALERT_THRESHOLD_SEC:
                    self.is_high_alert = True

            # ── 8. CONFIRMED / CANDIDATE → RECOVERING (hạ hông < 12% hoặc mất hỗ trợ) ──
            if self.state in ("CANDIDATE", "CONFIRMED") and (hip_drop < 0.12 or not has_support):
                self.state = "RECOVERING"
                self.recovering_start_time = now

            # ── 9. RECOVERING → NORMAL (hạ hông < 8% duy trì liên tục >= 3s) ──
            if self.state == "RECOVERING":
                if hip_drop < 0.08:
                    if self.recovering_start_time is None:
                        self.recovering_start_time = now
                    elif now - self.recovering_start_time >= 3.0:
                        # Phục hồi hoàn toàn về NORMAL
                        self.state = "NORMAL"
                        self.recovering_start_time = None
                        self.candidate_start_time = None
                        self.lowering_start_time = None
                        self.session_id = f"sess_{self.track_id}_{int(now * 1000)}"
                        self.is_confirmed_event = False
                        self.is_high_alert = False
                        self.is_preliminary_alert = False
                else:
                    # Nếu quay lại tư thế thấp trong lúc phục hồi
                    if hip_drop >= 0.15 and has_support:
                        self.state = "CANDIDATE" if not self.is_confirmed_event else "CONFIRMED"
                        self.recovering_start_time = None

        else:
            # Frame không hợp lệ (hông conf < 0.60) -> ghi nhận UNKNOWN, tạm dừng counter
            self.history.append((now, False, False, 0.0, "Khong xac dinh", 0.0))

    def handle_unseen(self, now: float):
        """Xử lý khi không thấy detection trong frame hiện tại."""
        self.unseen_duration = now - self.last_seen
        if self.unseen_duration <= UNSEEN_TOLERANCE_SEC:
            # Che khuất tạm thời (< 0.5s): duy trì Track ID, tạm dừng counter
            pass
        elif UNSEEN_TOLERANCE_SEC < self.unseen_duration <= 1.5:
            # Đóng băng trạng thái gần nhất
            pass
        else:
            # Quá 1.5s -> LOST
            if self.state != "LOST":
                self.state = "LOST"
                if self.is_confirmed_event:
                    self.event_ended_reason = "kết thúc do mất quan sát"


# ════════════════════════════════════════════════════════════
# CLASS: PoseAnalyzer — Engine chính (v3.0: YOLOv8 + ByteTrack)
# ════════════════════════════════════════════════════════════
class PoseAnalyzer:
    """
    Phân tích tư thế đa người dùng YOLOv8m-Pose + ByteTrack.
    """

    # ── Khởi tạo ─────────────────────────────────────────────
    def __init__(self):
        self._use_yolo     = False
        self._use_mediapipe = False
        self._model        = None   # YOLO model
        self._landmarker   = None   # MediaPipe fallback

        # Track state machine map: track_id -> PersonTrackState
        self.track_states: dict[int, PersonTrackState] = {}

        # Thử load YOLOv8 trước
        self._load_yolo()

        # Nếu YOLOv8 thất bại → thử MediaPipe fallback
        if not self._use_yolo:
            self._load_mediapipe_fallback()

        if not self._use_yolo and not self._use_mediapipe:
            raise RuntimeError(
                "Không load được model nào!\n"
                f"  YOLOv8: {_YOLO_MODEL_PATH}\n"
                f"  MediaPipe: {_MEDIAPIPE_MODEL_PATH}\n"
                "Hãy chạy: python download_model.py"
            )

        # ── Per-track state ────────────────────────────────────
        self._temporal_buffers: dict[int, TemporalBuffer]    = {}  # track_id → dwell buffer
        self._angle_buffers:    dict[int, AngleHistoryBuffer] = {}  # track_id → angle smoothing
        self._track_age:        dict[int, int]                = {}  # track_id → số frame liên tục

        # Kết quả frame hiện tại
        self.persons: dict = {}
        self.last_frame    = None
        self._timestamp_ms = 0
        self._blink_frame = 0

    # ── Load model ────────────────────────────────────────────
    def _load_yolo(self):
        """
        Thử load YOLOv8m-pose.pt.
        Nếu file chưa có → Ultralytics tự tải về (cần internet lần đầu).
        """
        try:
            from ultralytics import YOLO  # type: ignore

            # Nếu file model đã tồn tại cục bộ → dùng path đó
            # Nếu chưa có → truyền tên model để Ultralytics tự tải
            if os.path.exists(_YOLO_MODEL_PATH):
                self._model = YOLO(_YOLO_MODEL_PATH)
            else:
                print("[PoseAnalyzer] Chua co yolov8m-pose.pt, Ultralytics se tu tai...")
                self._model = YOLO('yolov8m-pose.pt')
                # Lưu lại vào thư mục models/ để lần sau dùng offline
                os.makedirs(_MODEL_DIR, exist_ok=True)
                # Ultralytics lưu model vào ~/.ultralytics/; copy sang models/
                import shutil
                import glob
                matches = glob.glob(os.path.expanduser('~/.ultralytics/assets/yolov8m-pose.pt'))
                if not matches:
                    # Thử tìm trong thư mục làm việc hiện tại
                    matches = glob.glob('yolov8m-pose.pt')
                if matches:
                    shutil.copy(matches[0], _YOLO_MODEL_PATH)
                    print(f"[PoseAnalyzer] Da luu model vao: {_YOLO_MODEL_PATH}")

            self._use_yolo = True
            print(f"[PoseAnalyzer] YOLOv8m-Pose: DA TAI THANH CONG")
        except Exception as e:
            print(f"[PoseAnalyzer] YOLOv8 load that bai: {e}")
            self._use_yolo = False

    def _load_mediapipe_fallback(self):
        """Fallback: load MediaPipe Pose nếu YOLOv8 không dùng được."""
        if not os.path.exists(_MEDIAPIPE_MODEL_PATH):
            print(f"[PoseAnalyzer] MediaPipe model khong tim thay: {_MEDIAPIPE_MODEL_PATH}")
            return
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import (
                PoseLandmarker, PoseLandmarkerOptions, RunningMode
            )
            options = PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=_MEDIAPIPE_MODEL_PATH),
                running_mode=RunningMode.VIDEO,
                num_poses=6,
                min_pose_detection_confidence=0.45,
                min_pose_presence_confidence=0.40,
                min_tracking_confidence=0.45,
                output_segmentation_masks=False,
            )
            self._landmarker    = PoseLandmarker.create_from_options(options)
            self._use_mediapipe = True
            print("[PoseAnalyzer] FALLBACK: MediaPipe Pose da bat")
        except Exception as e:
            print(f"[PoseAnalyzer] MediaPipe fallback that bai: {e}")
            self._use_mediapipe = False

    # ── Xử lý frame chính ─────────────────────────────────────
    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Nhận BGR frame, trả về frame đã vẽ skeleton + bounding box.
        Kết quả per-person lưu tại self.persons.
        """
        self.last_frame = frame.copy()
        self._blink_frame = (self._blink_frame + 1) % 20

        if self._use_yolo:
            return self._process_yolo(frame)
        elif self._use_mediapipe:
            return self._process_mediapipe(frame)
        else:
            return frame

    # ── Pipeline YOLOv8 ──────────────────────────────────────
    def _process_yolo(self, frame: np.ndarray) -> np.ndarray:
        """Xử lý frame với YOLOv8-Pose + ByteTrack."""
        h, w = frame.shape[:2]

        # ── Chạy YOLOv8 Track (ByteTrack tích hợp) ──────────
        # model.track() trả về list Results; persist=True giữ ByteTrack state giữa các frame
        try:
            results = self._model.track(
                frame,
                conf         = YOLO_CONF,
                iou          = YOLO_IOU,
                agnostic_nms = YOLO_AGNOSTIC_NMS,
                max_det      = YOLO_MAX_DET,
                imgsz        = 640,     # Resize về 640x640 theo đúng đặc tả kỹ thuật
                tracker      = "bytetrack.yaml",
                persist      = True,
                verbose      = False,
                classes      = [0],     # chỉ detect class 0 = "person"
            )
        except Exception as e:
            print(f"[PoseAnalyzer] YOLO track loi: {e}")
            return frame

        result = results[0] if results else None
        if result is None or result.boxes is None:
            self.persons = {}
            self._draw_hud(frame, 0)
            return frame

        # ── Lấy danh sách detection ──────────────────────────
        boxes      = result.boxes          # Boxes object
        keypoints  = result.keypoints      # Keypoints object (None nếu chỉ detect)

        # IDs từ ByteTrack (có thể None nếu track chưa gán)
        track_ids  = boxes.id.cpu().numpy().astype(int).tolist() \
                     if boxes.id is not None else list(range(len(boxes)))

        bboxes_xyxy = boxes.xyxy.cpu().numpy()   # (N, 4) — (x1,y1,x2,y2)

        # Keypoints: shape (N, 17, 3) — x, y, conf
        kpts_data = keypoints.data.cpu().numpy() if keypoints is not None else None

        # ── Nhiệm vụ 1b: Lọc detection có ít keypoint tin cậy ──
        if kpts_data is not None:
            kpts_xy   = kpts_data[:, :, :2]     # (N, 17, 2) — pixel
            kpts_conf = kpts_data[:, :, 2]       # (N, 17) — confidence
            valid_mask = filter_low_confidence_persons(
                kpts_xy, kpts_conf, bboxes_xyxy,
                min_kpts   = MIN_KPTS_VALID,
                kpt_conf_th = KPT_CONF_THRESHOLD,
            )
        else:
            valid_mask = [True] * len(bboxes_xyxy)

        # ── Cập nhật track_age và loại bỏ track non-conform ──
        current_ids = set()
        persons_new = {}
        now = time.time()

        for i, tid in enumerate(track_ids):
            if not valid_mask[i]:
                continue   # Bỏ qua detection giả keypoint ít

            current_ids.add(tid)

            # Cập nhật hoặc tạo mới PersonTrackState
            if tid not in self.track_states:
                self.track_states[tid] = PersonTrackState(tid)
            track_state = self.track_states[tid]

            # Cập nhật số frame liên tục
            self._track_age[tid] = self._track_age.get(tid, 0) + 1
            confirmed = track_state.state != "UNCONFIRMED" or self._track_age[tid] >= K_FRAME_CONFIRM

            # Bbox
            x1, y1, x2, y2 = bboxes_xyxy[i].astype(int)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            # Keypoints của detection này
            person_kpts  = kpts_xy[i]   if kpts_data is not None else None    # (17, 2)
            person_confs = kpts_conf[i]  if kpts_data is not None else np.zeros(17)  # (17,)

            # Tính vận tốc hạ hông chuẩn hóa (body-height/s)
            v_hip = track_state.compute_hip_velocity(person_kpts, person_confs, now)

            # ── Phân loại tư thế với BasePose, Vận tốc & Visibility check ──
            pose_result = {"label": "Khong phat hien", "confidence": 0.0, "is_valid_frame": False, "angle_debug": {}}
            hip_norm    = None
            wrist_norm  = None
            feet_norm   = None

            if person_kpts is not None:
                if tid not in self._angle_buffers:
                    self._angle_buffers[tid] = AngleHistoryBuffer()

                pose_result = classify_posture(
                    keypoints      = person_kpts,
                    kpt_conf       = person_confs,
                    history_buffer = self._angle_buffers[tid],
                    frame_height   = h,
                    bbox           = (x1, y1, x2, y2),
                    base_pose      = track_state.base_pose,
                    v_hip          = v_hip,
                )

                # Tọa độ hông chuẩn hóa
                lhp_c = person_confs[KPT_LEFT_HIP]
                rhp_c = person_confs[KPT_RIGHT_HIP]
                if lhp_c >= 0.60 or rhp_c >= 0.60:
                    lhp = person_kpts[KPT_LEFT_HIP]
                    rhp = person_kpts[KPT_RIGHT_HIP]
                    mx  = ((lhp[0] * lhp_c + rhp[0] * rhp_c) / (lhp_c + rhp_c + 1e-7))
                    my  = ((lhp[1] * lhp_c + rhp[1] * rhp_c) / (lhp_c + rhp_c + 1e-7))
                    hip_norm = (float(mx / w), float(my / h))

                # Tọa độ vị trí CHÂN chuẩn hóa cho ROI check (Quy ước: ưu tiên mắt cá, fallback đáy bbox)
                lank_c = person_confs[KPT_LEFT_ANKLE]
                rank_c = person_confs[KPT_RIGHT_ANKLE]
                if lank_c >= 0.50 and rank_c >= 0.50:
                    fx = (person_kpts[KPT_LEFT_ANKLE][0] + person_kpts[KPT_RIGHT_ANKLE][0]) / 2.0
                    fy = (person_kpts[KPT_LEFT_ANKLE][1] + person_kpts[KPT_RIGHT_ANKLE][1]) / 2.0
                    feet_norm = (float(fx / w), float(fy / h))
                elif lank_c >= 0.50:
                    feet_norm = (float(person_kpts[KPT_LEFT_ANKLE][0] / w), float(person_kpts[KPT_LEFT_ANKLE][1] / h))
                elif rank_c >= 0.50:
                    feet_norm = (float(person_kpts[KPT_RIGHT_ANKLE][0] / w), float(person_kpts[KPT_RIGHT_ANKLE][1] / h))
                else:
                    feet_norm = (float(cx / w), float(y2 / h))  # Điểm chính giữa cạnh dưới Bounding Box

                # Tọa độ cổ tay chuẩn hóa
                lwr_c = person_confs[KPT_LEFT_WRIST]
                rwr_c = person_confs[KPT_RIGHT_WRIST]
                if lwr_c >= MIN_KPT_VIS or rwr_c >= MIN_KPT_VIS:
                    if lwr_c >= rwr_c:
                        wx, wy = person_kpts[KPT_LEFT_WRIST]
                    else:
                        wx, wy = person_kpts[KPT_RIGHT_WRIST]
                    wrist_norm = (float(wx / w), float(wy / h))

                if confirmed:
                    self._draw_skeleton_yolo(frame, person_kpts, person_confs, w, h)

            # Cập nhật máy trạng thái hành vi
            track_state.update(pose_result, now)

            # Cập nhật TemporalBuffer
            if tid not in self._temporal_buffers:
                self._temporal_buffers[tid] = TemporalBuffer()
            self._temporal_buffers[tid].update(cy / h if h > 0 else 0.5)

            is_stooping = track_state.is_confirmed_event or self._temporal_buffers[tid].is_stooping()

            # Chỉ đưa vào persons_new nếu đã confirmed hoặc state đã vượt UNCONFIRMED
            if confirmed:
                persons_new[tid] = {
                    'pose':                 pose_result["label"],
                    'confidence':           pose_result["confidence"],
                    'bbox':                 (x1, y1, x2, y2),
                    'hip_norm':             hip_norm,
                    'feet_norm':            feet_norm,
                    'wrist_norm':           wrist_norm,
                    'is_stooping':          is_stooping,
                    'state':                track_state.state,
                    'session_id':           track_state.session_id,
                    'is_confirmed_event':   track_state.is_confirmed_event,
                    'is_high_alert':        track_state.is_high_alert,
                    'is_preliminary_alert': track_state.is_preliminary_alert,
                    'event_ended_reason':   track_state.event_ended_reason,
                    'centroid':             (cx, cy),
                    'confirmed':            True,
                    'v_hip':                v_hip,
                    'angle_debug':          pose_result["angle_debug"],
                }
                self._draw_person_box(
                    frame, tid,
                    x1, y1, x2, y2,
                    pose_result["label"],
                    pose_result["confidence"],
                    is_stooping,
                )
            else:
                cv2.rectangle(frame, (x1, y1), (x2, y2), C_UNCONFIRMED, 1)

        # ── Xử lý các track không xuất hiện trong frame ───────
        unseen_ids = set(self.track_states.keys()) - current_ids
        for tid in unseen_ids:
            self.track_states[tid].handle_unseen(now)
            if self.track_states[tid].state == "LOST" and (now - self.track_states[tid].last_seen > 10.0):
                self.track_states.pop(tid, None)
                self._track_age.pop(tid, None)
                self._temporal_buffers.pop(tid, None)
                self._angle_buffers.pop(tid, None)

        self.persons = persons_new

        # ── Vẽ HUD tổng hợp ─────────────────────────────────
        n_confirmed = len(persons_new)
        self._draw_hud(frame, n_confirmed)
        return frame

    # ── Pipeline MediaPipe (Fallback) ─────────────────────────
    def _process_mediapipe(self, frame: np.ndarray) -> np.ndarray:
        """
        Fallback: xử lý bằng MediaPipe Pose (v2.0 logic).
        Chỉ kích hoạt khi YOLOv8 không load được.
        Dùng lại logic cũ với CentroidTracker thủ công.
        """
        import mediapipe as mp
        from collections import OrderedDict

        h, w = frame.shape[:2]
        self._timestamp_ms += 33

        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        try:
            mp_result = self._landmarker.detect_for_video(mp_image, self._timestamp_ms)
        except Exception:
            return frame

        # Khởi tạo CentroidTracker nếu chưa có (chỉ dùng trong fallback)
        if not hasattr(self, '_mp_tracker'):
            self._mp_tracker = _CentroidTrackerLegacy(max_disappeared=40, max_distance=120)

        rects    = []
        all_lms  = []
        all_hips = []

        # MediaPipe Pose indices (33 kpts)
        MP_L_HIP = 23; MP_R_HIP = 24
        MP_L_SH  = 11; MP_R_SH  = 12
        MP_L_KN  = 25; MP_R_KN  = 26
        MP_L_ANK = 27; MP_R_ANK = 28

        if mp_result.pose_landmarks:
            for lms in mp_result.pose_landmarks:
                xs  = [lm.x * w for lm in lms]
                ys  = [lm.y * h for lm in lms]
                pad = 18
                x1  = max(0, int(min(xs)) - pad)
                y1  = max(0, int(min(ys)) - pad)
                x2  = min(w, int(max(xs)) + pad)
                y2  = min(h, int(max(ys)) + pad)
                rects.append((x1, y1, x2, y2))
                all_lms.append(lms)
                hl = lms[MP_L_HIP]; hr = lms[MP_R_HIP]
                all_hips.append((float((hl.x + hr.x) / 2), float((hl.y + hr.y) / 2)))

        tracked = self._mp_tracker.update(rects)
        self.persons = {}

        for pid, (cx, cy, x1, y1, x2, y2) in tracked.items():
            lms_match = None; hip_match = None; min_d = float('inf')
            for i, rect in enumerate(rects):
                rcx = (rect[0] + rect[2]) // 2; rcy = (rect[1] + rect[3]) // 2
                d   = np.sqrt((cx - rcx)**2 + (cy - rcy)**2)
                if d < min_d:
                    min_d = d; lms_match = all_lms[i]; hip_match = all_hips[i]

            # Vẽ skeleton MediaPipe đơn giản
            if lms_match is not None:
                self._draw_skeleton_mediapipe(frame, lms_match, w, h)

            # Phân loại tư thế bằng MediaPipe 33 kpts (logic cũ từ v2.0)
            pose, conf = self._classify_mediapipe(lms_match, w, h) if lms_match else ('Khong phat hien', 0.0)

            if pid not in self._temporal_buffers:
                self._temporal_buffers[pid] = TemporalBuffer()
            self._temporal_buffers[pid].update(cy / h if h > 0 else 0.5)
            is_stooping = self._temporal_buffers[pid].is_stooping()

            self.persons[pid] = {
                'pose':        pose,
                'confidence':  conf,
                'bbox':        (x1, y1, x2, y2),
                'hip_norm':    hip_match,
                'wrist_norm':  None,
                'is_stooping': is_stooping,
                'centroid':    (cx, cy),
                'confirmed':   True,
                'angle_debug': {"mode": "mediapipe_fallback"},
            }
            self._draw_person_box(frame, pid, x1, y1, x2, y2, pose, conf, is_stooping)

        dead_mp = set(self._temporal_buffers.keys()) - set(tracked.keys())
        for d in dead_mp:
            self._temporal_buffers.pop(d, None)

        self._draw_hud(frame, len(tracked))
        return frame

    # ── Phân loại MediaPipe (legacy — chỉ dùng khi fallback) ─
    def _classify_mediapipe(self, lms, w, h):
        """Phân loại tư thế bằng MediaPipe 33 kpts (giữ lại từ v2.0 cho fallback)."""
        MIN_VIS = 0.35
        ANGLE_KNEELING_MAX = 95; ANGLE_BOWING_MAX = 55
        ANGLE_SITTING_MIN = 75; ANGLE_STANDING_MIN = 158

        def xy(idx): return int(lms[idx].x * w), int(lms[idx].y * h)
        def vis(idx): return getattr(lms[idx], 'visibility', 1.0)

        vis_l = vis(23); vis_r = vis(24)
        if max(vis_l, vis_r) < MIN_VIS:
            return 'Khong xac dinh', 0.0

        side = 'L' if vis_l >= vis_r else 'R'
        if side == 'L':
            sh, hp, kn, ank = xy(11), xy(23), xy(25), xy(27)
        else:
            sh, hp, kn, ank = xy(12), xy(24), xy(26), xy(28)

        def _angle(a, b, c):
            a, b, c = np.array(a, float), np.array(b, float), np.array(c, float)
            ba, bc = a - b, c - b
            cos_v = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-7)
            return float(np.degrees(np.arccos(np.clip(cos_v, -1.0, 1.0))))

        angle_knee = _angle(hp, kn, ank)
        angle_hip  = _angle(sh, hp, kn)
        sh_m = ((xy(11)[0] + xy(12)[0]) // 2, (xy(11)[1] + xy(12)[1]) // 2)
        hp_m = ((xy(23)[0] + xy(24)[0]) // 2, (xy(23)[1] + xy(24)[1]) // 2)
        trunk = np.array([sh_m[0] - hp_m[0], sh_m[1] - hp_m[1]], float)
        vert  = np.array([0.0, -1.0])
        cos_t = np.dot(trunk, vert) / (np.linalg.norm(trunk) + 1e-7)
        angle_trunk = float(np.degrees(np.arccos(np.clip(cos_t, -1.0, 1.0))))

        if angle_knee < ANGLE_KNEELING_MAX:
            return 'Quy', float(round(min(1.0, (ANGLE_KNEELING_MAX - angle_knee) / ANGLE_KNEELING_MAX) * 100, 1))
        if angle_trunk < ANGLE_BOWING_MAX:
            return 'Cui nguoi', float(round(min(1.0, (ANGLE_BOWING_MAX - angle_trunk) / ANGLE_BOWING_MAX) * 100, 1))
        if ANGLE_SITTING_MIN <= angle_hip <= ANGLE_STANDING_MIN:
            return 'Ngoi', float(round(max(0.3, 1.0 - abs(angle_hip - 110) / 50) * 100, 1))
        return 'Dung', float(round(min(1.0, max(0.5, (angle_hip - ANGLE_STANDING_MIN) / 40 + 0.5)) * 100, 1))

    # ── Vẽ skeleton YOLOv8 COCO 17 kpts ──────────────────────
    def _draw_skeleton_yolo(self, frame, kpts, confs, w, h):
        """Vẽ skeleton từ 17 keypoint COCO của YOLOv8-Pose."""
        # Vẽ đường nối
        for (a_i, b_i) in COCO_CONNECTIONS:
            if confs[a_i] >= MIN_KPT_VIS and confs[b_i] >= MIN_KPT_VIS:
                pa = (int(kpts[a_i][0]), int(kpts[a_i][1]))
                pb = (int(kpts[b_i][0]), int(kpts[b_i][1]))
                # Bỏ qua nếu tọa độ nằm ngoài frame (keypoint bị extrapolate)
                if 0 <= pa[0] < w and 0 <= pa[1] < h and 0 <= pb[0] < w and 0 <= pb[1] < h:
                    cv2.line(frame, pa, pb, C_CONNECT, 2, cv2.LINE_AA)
        # Vẽ điểm keypoint
        for idx in range(17):
            if confs[idx] >= MIN_KPT_VIS:
                px = int(kpts[idx][0]); py = int(kpts[idx][1])
                if 0 <= px < w and 0 <= py < h:
                    cv2.circle(frame, (px, py), 4, C_LANDMARK, -1, cv2.LINE_AA)

    # ── Vẽ skeleton MediaPipe (legacy fallback) ───────────────
    def _draw_skeleton_mediapipe(self, frame, lms, w, h):
        MP_CONNECTIONS = [
            (11, 12), (11, 23), (12, 24), (23, 24),
            (23, 25), (25, 27), (24, 26), (26, 28),
            (11, 13), (13, 15), (12, 14), (14, 16),
        ]
        MIN_VIS = 0.35
        for a_i, b_i in MP_CONNECTIONS:
            if getattr(lms[a_i], 'visibility', 1.0) >= MIN_VIS and getattr(lms[b_i], 'visibility', 1.0) >= MIN_VIS:
                pa = (int(lms[a_i].x * w), int(lms[a_i].y * h))
                pb = (int(lms[b_i].x * w), int(lms[b_i].y * h))
                cv2.line(frame, pa, pb, C_CONNECT, 2, cv2.LINE_AA)
                cv2.circle(frame, pa, 4, C_LANDMARK, -1, cv2.LINE_AA)
                cv2.circle(frame, pb, 4, C_LANDMARK, -1, cv2.LINE_AA)

    # ── Vẽ bounding box + nhãn từng người ─────────────────────
    def _draw_person_box(self, frame, pid, x1, y1, x2, y2, pose, conf, is_stooping):
        POSE_VN = {
            'Dung':         'DUNG',
            'Ngoi':         'NGOI',
            'Cui nguoi':    'CUI NGUOI',
            'Quy':          'QUY',
            'Khong phat hien': '?',
            'Khong xac dinh':  '?',
        }
        label_vn = POSE_VN.get(pose, pose.upper())

        if is_stooping:
            color     = C_ALERT_BOX if (self._blink_frame < 10) else (0, 50, 180)
            thickness = 3
        elif pose in ('Cui nguoi', 'Quy', 'Ngoi'):
            color     = (0, 165, 255)   # Cam — đang theo dõi, chưa đủ thời gian
            thickness = 2
        else:
            color     = C_NORMAL_BOX
            thickness = 2

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        label_text = f"P{pid} | {label_vn}"
        if is_stooping:
            label_text += " [!VI PHAM]"
        (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)
        cv2.putText(frame, label_text, (x1 + 3, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, C_ID_TEXT, 1, cv2.LINE_AA)

        # Thanh confidence
        bar_w = int((x2 - x1) * conf / 100)
        cv2.rectangle(frame, (x1, y2 + 2), (x1 + bar_w, y2 + 6), color, -1)

    # ── HUD tổng hợp ──────────────────────────────────────────
    def _draw_hud(self, frame, n_persons):
        n_alert = sum(1 for p in self.persons.values() if p.get('is_stooping'))
        backend = "YOLO" if self._use_yolo else "MP-Fallback"
        ov = frame.copy()
        cv2.rectangle(ov, (8, 8), (260, 70), (0, 0, 0), -1)
        cv2.addWeighted(ov, 0.5, frame, 0.5, 0, frame)
        cv2.putText(frame, f"Phat hien: {n_persons} nguoi [{backend}]",
                    (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 255, 200), 1, cv2.LINE_AA)
        if n_alert > 0:
            cv2.putText(frame, f"VI PHAM: {n_alert} nguoi",
                        (14, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.58, C_ALERT_BOX, 2, cv2.LINE_AA)

    # ── API ra ngoài ──────────────────────────────────────────
    def get_snapshot_frame(self):
        return self.last_frame

    def get_result(self) -> dict:
        """
        Tương thích ngược với camera_service.py và alert_engine.py.
        Trả về người vi phạm đầu tiên (hoặc người đầu tiên nếu không ai vi phạm).
        Code mới nên đọc self.persons trực tiếp để xử lý đa người.
        """
        if not self.persons:
            return {
                'pose':        'Khong phat hien',
                'confidence':  0.0,
                'is_detected': False,
                'hip_norm':    None,
                'wrist_norm':  None,
                'person_bbox': None,
                'persons':     {},
            }

        # Ưu tiên người đang vi phạm
        for pid, info in self.persons.items():
            if info.get('is_stooping'):
                return {
                    'pose':        info['pose'],
                    'confidence':  info['confidence'],
                    'is_detected': True,
                    'hip_norm':    info['hip_norm'],
                    'wrist_norm':  info.get('wrist_norm'),
                    'person_bbox': info['bbox'],
                    'persons':     self.persons,
                }

        first = next(iter(self.persons.values()))
        return {
            'pose':        first['pose'],
            'confidence':  first['confidence'],
            'is_detected': True,
            'hip_norm':    first['hip_norm'],
            'wrist_norm':  first.get('wrist_norm'),
            'person_bbox': first['bbox'],
            'persons':     self.persons,
        }


# ════════════════════════════════════════════════════════════
# Legacy CentroidTracker (CHỈ dùng cho MediaPipe fallback)
# ════════════════════════════════════════════════════════════
class _CentroidTrackerLegacy:
    """CentroidTracker thủ công — giữ lại để MediaPipe fallback hoạt động."""

    def __init__(self, max_disappeared=40, max_distance=120):
        self.next_id     = 0
        self.objects     = OrderedDict()
        self.disappeared = OrderedDict()
        self.bboxes      = OrderedDict()
        self.max_dis     = max_disappeared
        self.max_dist    = max_distance

    def register(self, centroid, bbox):
        pid = self.next_id
        self.objects[pid]    = centroid
        self.disappeared[pid] = 0
        self.bboxes[pid]     = bbox
        self.next_id += 1

    def deregister(self, pid):
        del self.objects[pid]; del self.disappeared[pid]; del self.bboxes[pid]

    def update(self, rects):
        if len(rects) == 0:
            for pid in list(self.disappeared.keys()):
                self.disappeared[pid] += 1
                if self.disappeared[pid] > self.max_dis:
                    self.deregister(pid)
            return self._build()

        input_cents = [((x1+x2)//2, (y1+y2)//2) for x1,y1,x2,y2 in rects]

        if len(self.objects) == 0:
            for i, rect in enumerate(rects):
                self.register(input_cents[i], rect)
        else:
            ids = list(self.objects.keys())
            old = list(self.objects.values())
            D = np.zeros((len(old), len(input_cents)))
            for i,(ox,oy) in enumerate(old):
                for j,(nx,ny) in enumerate(input_cents):
                    D[i,j] = np.sqrt((ox-nx)**2 + (oy-ny)**2)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            ur = set(); uc = set()
            for r,c in zip(rows, cols):
                if r in ur or c in uc: continue
                if D[r,c] > self.max_dist: continue
                pid = ids[r]
                self.objects[pid] = input_cents[c]
                self.bboxes[pid]  = rects[c]
                self.disappeared[pid] = 0
                ur.add(r); uc.add(c)
            for r in set(range(D.shape[0])) - ur:
                pid = ids[r]
                self.disappeared[pid] += 1
                if self.disappeared[pid] > self.max_dis:
                    self.deregister(pid)
            for c in set(range(D.shape[1])) - uc:
                self.register(input_cents[c], rects[c])
        return self._build()

    def _build(self):
        result = {}
        for pid in self.objects:
            cx, cy = self.objects[pid]
            x1,y1,x2,y2 = self.bboxes[pid]
            result[pid] = (cx, cy, x1, y1, x2, y2)
        return result
