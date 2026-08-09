# ============================================================
# app/services/pose_analyzer.py — Phân tích tư thế đa người
#
# Kiến trúc mới (v2.0):
#   MediaPipe Pose (N người) → CentroidTracker (gán ID) →
#   TemporalBuffer (Buffer 5s chống báo giả) → Kết quả dict per person_id
#
# Tương thích MediaPipe Tasks API >= 0.10
# Model: models/pose_landmarker_lite.task
# ============================================================
import numpy as np
import cv2
import os
import time
from collections import deque, OrderedDict

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

# ─── Cấu hình AI ──────────────────────────────────────────
MAX_PERSONS         = 6      # Tối đa 6 người (1 camera quét cả phòng)
MIN_VISIBILITY      = 0.35   # Ngưỡng tin cậy keypoint (thấp hơn = nhạy hơn)
SMOOTH_FRAMES       = 4      # Số frame liên tiếp để chốt tư thế
MAX_DISAPPEARED     = 40     # Số frame biến mất trước khi hủy ID

# ─── Cấu hình Temporal Buffer ──────────────────────────────
BUFFER_SECONDS      = 5.0    # Giữ dữ liệu 5 giây gần nhất
STOOP_THRESHOLD_SEC = 3.0    # Cúi ≥ 3s liên tục → vi phạm
STOOP_DROP_RATIO    = 0.05   # Tâm phải hạ xuống ≥ 5% chiều cao frame để tính là "đang cúi"

# ─── Ngưỡng phân loại tư thế ───────────────────────────────
ANGLE_STANDING_MIN  = 158
ANGLE_SITTING_MIN   = 75
ANGLE_BOWING_MAX    = 55
ANGLE_KNEELING_MAX  = 95

# ─── Màu sắc (BGR — OpenCV) ────────────────────────────────
C_LANDMARK   = (0, 212, 255)
C_CONNECT    = (100, 180, 255)
C_NORMAL_BOX = (50, 200, 50)      # Xanh lá — bình thường
C_ALERT_BOX  = (0, 0, 220)        # Đỏ — vi phạm / đang cúi
C_ID_TEXT    = (255, 255, 255)    # Trắng

# ─── Đường dẫn model ───────────────────────────────────────
_MODEL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'models', 'pose_landmarker_lite.task')
)

# ─── Chỉ số keypoint MediaPipe Pose (33 điểm) ──────────────
IDX_NOSE           = 0
IDX_LEFT_SHOULDER  = 11
IDX_RIGHT_SHOULDER = 12
IDX_LEFT_HIP       = 23
IDX_RIGHT_HIP      = 24
IDX_LEFT_KNEE      = 25
IDX_RIGHT_KNEE     = 26
IDX_LEFT_ANKLE     = 27
IDX_RIGHT_ANKLE    = 28
IDX_LEFT_ELBOW     = 13
IDX_RIGHT_ELBOW    = 14
IDX_LEFT_WRIST     = 15
IDX_RIGHT_WRIST    = 16


# ════════════════════════════════════════════════════════════
# CLASS 1: CentroidTracker — Gán ID cho từng người
# ════════════════════════════════════════════════════════════
class CentroidTracker:
    """
    Theo dõi nhiều đối tượng bằng khoảng cách Euclidean giữa tâm
    bounding box ở hai frame liên tiếp.

    Thuật toán:
    1. Mỗi frame nhận danh sách bounding boxes (x1,y1,x2,y2).
    2. Tính tâm (cx, cy) từng bbox.
    3. So sánh với tâm của các ID đang theo dõi:
       - Nếu khoảng cách < MAX_DISTANCE → giữ nguyên ID cũ
       - Nếu không khớp → cấp ID mới
    4. ID nào biến mất quá MAX_DISAPPEARED frame → bị hủy.

    Phức tạp: O(M×N) với M=ID đang theo dõi, N=bbox mới.
    """

    def __init__(self, max_disappeared=MAX_DISAPPEARED, max_distance=120):
        self.next_id       = 0
        self.objects       = OrderedDict()     # id → centroid (cx, cy)
        self.disappeared   = OrderedDict()     # id → số frame biến mất
        self.bboxes        = OrderedDict()     # id → (x1,y1,x2,y2)
        self.max_dis       = max_disappeared
        self.max_dist      = max_distance

    def register(self, centroid, bbox):
        pid = self.next_id
        self.objects[pid]    = centroid
        self.disappeared[pid] = 0
        self.bboxes[pid]     = bbox
        self.next_id += 1
        return pid

    def deregister(self, pid):
        del self.objects[pid]
        del self.disappeared[pid]
        del self.bboxes[pid]

    def update(self, rects):
        """
        Cập nhật tracker với danh sách bounding boxes mới.
        rects: [(x1,y1,x2,y2), ...]
        Trả về: {person_id: (cx, cy, x1, y1, x2, y2)}
        """
        # Không có detection nào
        if len(rects) == 0:
            for pid in list(self.disappeared.keys()):
                self.disappeared[pid] += 1
                if self.disappeared[pid] > self.max_dis:
                    self.deregister(pid)
            return self._build_result()

        # Tính tâm của các bbox mới
        input_centroids = []
        for (x1, y1, x2, y2) in rects:
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            input_centroids.append((cx, cy))

        # Chưa có ID nào → đăng ký tất cả
        if len(self.objects) == 0:
            for i, rect in enumerate(rects):
                self.register(input_centroids[i], rect)
        else:
            # So sánh và khớp ID
            ids         = list(self.objects.keys())
            old_centroids = list(self.objects.values())

            # Ma trận khoảng cách Euclidean
            D = np.zeros((len(old_centroids), len(input_centroids)))
            for i, (ox, oy) in enumerate(old_centroids):
                for j, (nx, ny) in enumerate(input_centroids):
                    D[i, j] = np.sqrt((ox - nx)**2 + (oy - ny)**2)

            # Khớp: hàng có min nhỏ nhất trước
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                if D[row, col] > self.max_dist:
                    continue

                pid = ids[row]
                self.objects[pid]    = input_centroids[col]
                self.bboxes[pid]     = rects[col]
                self.disappeared[pid] = 0
                used_rows.add(row)
                used_cols.add(col)

            # ID chưa được khớp → tăng disappeared
            unused_rows = set(range(D.shape[0])) - used_rows
            for row in unused_rows:
                pid = ids[row]
                self.disappeared[pid] += 1
                if self.disappeared[pid] > self.max_dis:
                    self.deregister(pid)

            # Bbox mới chưa được khớp → ID mới
            unused_cols = set(range(D.shape[1])) - used_cols
            for col in unused_cols:
                self.register(input_centroids[col], rects[col])

        return self._build_result()

    def _build_result(self):
        result = {}
        for pid in self.objects:
            cx, cy = self.objects[pid]
            x1, y1, x2, y2 = self.bboxes[pid]
            result[pid] = (cx, cy, x1, y1, x2, y2)
        return result


# ════════════════════════════════════════════════════════════
# CLASS 2: TemporalBuffer — Buffer 5s chống báo giả
# ════════════════════════════════════════════════════════════
class TemporalBuffer:
    """
    Lưu lịch sử tọa độ tâm Y của một người trong BUFFER_SECONDS giây.
    Phát hiện "cúi người liên tục" bằng phân tích xu hướng theo thời gian.

    Logic phát hiện vi phạm:
    - Loại bỏ các điểm cũ hơn BUFFER_SECONDS giây.
    - Nếu tọa độ Y hiện tại cao hơn Y trung bình của 1s đầu buffer
      thêm STOOP_DROP_RATIO (= người đang ở tư thế thấp hơn lúc đầu)
    - VÀ duy trì trạng thái đó liên tục ≥ STOOP_THRESHOLD_SEC giây.
    → Kết luận: vi phạm cúi gầm bàn.

    Trục Y trong OpenCV: 0 = trên cùng, tăng dần xuống dưới.
    """

    def __init__(self):
        # deque[(timestamp, y_center_normalized)]
        self.buffer: deque = deque()
        self.stoop_start: float | None = None   # Thời điểm bắt đầu trạng thái cúi

    def update(self, y_norm: float, frame_h: int = 1):
        """Thêm điểm dữ liệu mới và loại bỏ điểm quá cũ."""
        now = time.monotonic()
        self.buffer.append((now, y_norm))
        # Xóa các điểm cũ hơn BUFFER_SECONDS
        cutoff = now - BUFFER_SECONDS
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    def is_stooping(self, threshold_sec: float = STOOP_THRESHOLD_SEC) -> bool:
        """
        Kiểm tra người đang ở tư thế thấp liên tục ≥ threshold_sec giây.
        Trả về True nếu vi phạm.
        """
        if len(self.buffer) < 3:
            return False

        now = time.monotonic()

        # Lấy Y trung bình của 1 giây đầu trong buffer (baseline)
        baseline_pts = [y for t, y in self.buffer if t <= self.buffer[0][0] + 1.0]
        if not baseline_pts:
            return False
        baseline_y = float(np.mean(baseline_pts))

        # Y hiện tại (trung bình 0.5s cuối)
        cutoff_recent = now - 0.5
        recent_pts = [y for t, y in self.buffer if t >= cutoff_recent]
        if not recent_pts:
            return False
        current_y = float(np.mean(recent_pts))

        # Người đang thấp hơn baseline STOOP_DROP_RATIO
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
# CLASS 3: PoseAnalyzer — Engine chính
# ════════════════════════════════════════════════════════════
class PoseAnalyzer:
    """
    Phân tích tư thế đa người (Multi-Person Pose Analysis).

    Mỗi frame trả về:
    {
      person_id: {
        'pose':       str,       # 'Dung' | 'Ngoi' | 'Cui nguoi' | 'Quy' | ...
        'confidence': float,
        'bbox':       (x1,y1,x2,y2),  # pixel
        'hip_norm':   (x, y),          # tọa độ chuẩn hóa 0–1
        'is_stooping':bool,            # Buffer 5s đã xác nhận cúi liên tục
        'centroid':   (cx, cy),
      }
    }
    """

    def __init__(self):
        if not os.path.exists(_MODEL_PATH):
            raise FileNotFoundError(
                f"Không tìm thấy model MediaPipe tại: {_MODEL_PATH}\n"
                "Hãy chạy: python download_model.py"
            )

        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_MODEL_PATH),
            running_mode=RunningMode.VIDEO,
            num_poses=MAX_PERSONS,
            min_pose_detection_confidence=0.45,
            min_pose_presence_confidence=0.40,
            min_tracking_confidence=0.45,
            output_segmentation_masks=False,
        )
        self.landmarker = PoseLandmarker.create_from_options(options)

        self._timestamp_ms  = 0
        self._tracker       = CentroidTracker(max_disappeared=MAX_DISAPPEARED, max_distance=120)
        self._buffers: dict[int, TemporalBuffer] = {}    # person_id → buffer
        self._smooth_hist: dict[int, deque]       = {}   # person_id → label history

        # Kết quả frame hiện tại
        self.persons: dict      = {}
        self.last_frame         = None

        # Blink state (đèn nháy khi vi phạm)
        self._blink_frame = 0

    # ── Tiện ích ──────────────────────────────────────────────
    def _calc_angle(self, a, b, c):
        a, b, c = np.array(a, float), np.array(b, float), np.array(c, float)
        ba, bc = a - b, c - b
        cos_v = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-7)
        return np.degrees(np.arccos(np.clip(cos_v, -1.0, 1.0)))

    def _lm_xy(self, lms, idx, w, h):
        lm = lms[idx]
        return int(lm.x * w), int(lm.y * h)

    def _lm_vis(self, lms, idx):
        return getattr(lms[idx], 'visibility', 1.0)

    # ── Phân loại tư thế ──────────────────────────────────────
    def _classify(self, lms, w, h):
        vis_l = self._lm_vis(lms, IDX_LEFT_HIP)
        vis_r = self._lm_vis(lms, IDX_RIGHT_HIP)
        side  = 'L' if vis_l >= vis_r else 'R'

        def xy(idx): return self._lm_xy(lms, idx, w, h)
        def vis(idx): return self._lm_vis(lms, idx)

        if side == 'L':
            sh, hp, kn, ank = xy(IDX_LEFT_SHOULDER), xy(IDX_LEFT_HIP), xy(IDX_LEFT_KNEE), xy(IDX_LEFT_ANKLE)
        else:
            sh, hp, kn, ank = xy(IDX_RIGHT_SHOULDER), xy(IDX_RIGHT_HIP), xy(IDX_RIGHT_KNEE), xy(IDX_RIGHT_ANKLE)

        hp_vis = max(vis_l, vis_r)
        if hp_vis < MIN_VISIBILITY:
            return 'Khong xac dinh', 0.0

        angle_knee = self._calc_angle(hp, kn, ank)
        angle_hip  = self._calc_angle(sh, hp, kn)

        sh_l = xy(IDX_LEFT_SHOULDER);  sh_r = xy(IDX_RIGHT_SHOULDER)
        hp_l = xy(IDX_LEFT_HIP);       hp_r = xy(IDX_RIGHT_HIP)
        sh_m = ((sh_l[0] + sh_r[0]) // 2, (sh_l[1] + sh_r[1]) // 2)
        hp_m = ((hp_l[0] + hp_r[0]) // 2, (hp_l[1] + hp_r[1]) // 2)
        trunk = np.array([sh_m[0] - hp_m[0], sh_m[1] - hp_m[1]], float)
        vert  = np.array([0.0, -1.0])
        cos_t = np.dot(trunk, vert) / (np.linalg.norm(trunk) + 1e-7)
        angle_trunk = np.degrees(np.arccos(np.clip(cos_t, -1.0, 1.0)))

        if angle_knee < ANGLE_KNEELING_MAX:
            conf = min(1.0, (ANGLE_KNEELING_MAX - angle_knee) / ANGLE_KNEELING_MAX)
            return 'Quy', float(round(conf * 100, 1))
        if angle_trunk < ANGLE_BOWING_MAX:
            conf = min(1.0, (ANGLE_BOWING_MAX - angle_trunk) / ANGLE_BOWING_MAX)
            return 'Cui nguoi', float(round(conf * 100, 1))
        if ANGLE_SITTING_MIN <= angle_hip <= ANGLE_STANDING_MIN:
            dist = abs(angle_hip - 110)
            conf = max(0.3, 1.0 - dist / 50)
            return 'Ngoi', float(round(conf * 100, 1))
        conf = min(1.0, max(0.5, (angle_hip - ANGLE_STANDING_MIN) / 40 + 0.5))
        return 'Dung', float(round(conf * 100, 1))

    def _smooth_label(self, pid: int, label: str) -> str:
        if pid not in self._smooth_hist:
            self._smooth_hist[pid] = deque(maxlen=SMOOTH_FRAMES)
        hist = self._smooth_hist[pid]
        hist.append(label)
        if len(hist) == SMOOTH_FRAMES and len(set(hist)) == 1:
            return label
        return hist[-2] if len(hist) >= 2 else label

    # ── Xử lý frame chính ─────────────────────────────────────
    def process_frame(self, frame):
        """
        Nhận BGR frame, trả về frame đã vẽ annotations.
        Kết quả per-person có tại self.persons.
        """
        h, w = frame.shape[:2]
        self._timestamp_ms += 33
        self.last_frame = frame.copy()

        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result   = self.landmarker.detect_for_video(mp_image, self._timestamp_ms)

        rects     = []   # bounding boxes phát hiện được
        all_lms   = []   # landmarks tương ứng
        all_hips  = []   # hip_norm tương ứng

        if result.pose_landmarks:
            for lms in result.pose_landmarks:
                xs  = [lm.x * w for lm in lms]
                ys  = [lm.y * h for lm in lms]
                pad = 18
                x1  = max(0, int(min(xs)) - pad)
                y1  = max(0, int(min(ys)) - pad)
                x2  = min(w, int(max(xs)) + pad)
                y2  = min(h, int(max(ys)) + pad)
                rects.append((x1, y1, x2, y2))
                all_lms.append(lms)

                # Tọa độ hông chuẩn hóa
                hl = lms[IDX_LEFT_HIP];  hr = lms[IDX_RIGHT_HIP]
                all_hips.append((float((hl.x + hr.x) / 2), float((hl.y + hr.y) / 2)))

        # Cập nhật CentroidTracker
        tracked = self._tracker.update(rects)  # {pid: (cx,cy,x1,y1,x2,y2)}

        # Khớp pid với landmarks (gần nhất)
        self.persons = {}
        self._blink_frame = (self._blink_frame + 1) % 20   # chu kỳ blink 20 frame

        for pid, (cx, cy, x1, y1, x2, y2) in tracked.items():
            # Tìm landmarks tương ứng bằng khoảng cách tâm
            lms_match  = None
            hip_match  = None
            min_dist   = float('inf')
            for i, rect in enumerate(rects):
                rcx = (rect[0] + rect[2]) // 2
                rcy = (rect[1] + rect[3]) // 2
                d   = np.sqrt((cx - rcx)**2 + (cy - rcy)**2)
                if d < min_dist:
                    min_dist   = d
                    lms_match  = all_lms[i]
                    hip_match  = all_hips[i]

            # Phân loại tư thế
            pose, conf = ('Khong phat hien', 0.0)
            if lms_match is not None:
                raw_pose, conf = self._classify(lms_match, w, h)
                pose = self._smooth_label(pid, raw_pose)
                self._draw_skeleton(frame, lms_match, w, h)

            # Cập nhật Temporal Buffer
            if pid not in self._buffers:
                self._buffers[pid] = TemporalBuffer()
            buf = self._buffers[pid]
            y_norm = cy / h if h > 0 else 0.5
            buf.update(y_norm)
            is_stooping = buf.is_stooping()

            # Dọn dẹp buffer của ID đã bị hủy
            active_ids = set(tracked.keys())
            for dead_pid in list(self._buffers.keys()):
                if dead_pid not in active_ids:
                    self._buffers[dead_pid].reset()

            # Ghi kết quả
            self.persons[pid] = {
                'pose':        pose,
                'confidence':  conf,
                'bbox':        (x1, y1, x2, y2),
                'hip_norm':    hip_match,
                'is_stooping': is_stooping,
                'centroid':    (cx, cy),
            }

            # Vẽ Bounding Box
            self._draw_person_box(frame, pid, x1, y1, x2, y2, pose, conf, is_stooping)

        # Vẽ HUD tổng
        self._draw_hud(frame, len(tracked))
        return frame

    # ── Vẽ skeleton ───────────────────────────────────────────
    def _draw_skeleton(self, frame, lms, w, h):
        connections = [
            (IDX_LEFT_SHOULDER,  IDX_RIGHT_SHOULDER),
            (IDX_LEFT_SHOULDER,  IDX_LEFT_HIP),
            (IDX_RIGHT_SHOULDER, IDX_RIGHT_HIP),
            (IDX_LEFT_HIP,       IDX_RIGHT_HIP),
            (IDX_LEFT_HIP,       IDX_LEFT_KNEE),
            (IDX_LEFT_KNEE,      IDX_LEFT_ANKLE),
            (IDX_RIGHT_HIP,      IDX_RIGHT_KNEE),
            (IDX_RIGHT_KNEE,     IDX_RIGHT_ANKLE),
            (IDX_LEFT_SHOULDER,  IDX_LEFT_ELBOW),
            (IDX_LEFT_ELBOW,     IDX_LEFT_WRIST),
            (IDX_RIGHT_SHOULDER, IDX_RIGHT_ELBOW),
            (IDX_RIGHT_ELBOW,    IDX_RIGHT_WRIST),
        ]
        for a_i, b_i in connections:
            if self._lm_vis(lms, a_i) >= MIN_VISIBILITY and self._lm_vis(lms, b_i) >= MIN_VISIBILITY:
                pa = self._lm_xy(lms, a_i, w, h)
                pb = self._lm_xy(lms, b_i, w, h)
                cv2.line(frame, pa, pb, C_CONNECT, 2, cv2.LINE_AA)
                cv2.circle(frame, pa, 4, C_LANDMARK, -1, cv2.LINE_AA)
                cv2.circle(frame, pb, 4, C_LANDMARK, -1, cv2.LINE_AA)

    # ── Vẽ bounding box + nhãn từng người ─────────────────────
    def _draw_person_box(self, frame, pid, x1, y1, x2, y2, pose, conf, is_stooping):
        POSE_VN = {
            'Dung': 'DUNG', 'Ngoi': 'NGOI',
            'Cui nguoi': 'CUI NGUOI', 'Quy': 'QUY',
            'Khong phat hien': '?', 'Khong xac dinh': '?',
        }
        label_vn = POSE_VN.get(pose, pose.upper())

        # Màu box và trạng thái
        if is_stooping:
            # Nhấp nháy đỏ khi vi phạm xác nhận
            color = C_ALERT_BOX if (self._blink_frame < 10) else (0, 50, 180)
            thickness = 3
        elif pose in ('Cui nguoi', 'Quy', 'Ngoi'):
            color = (0, 165, 255)   # Cam — đang theo dõi, chưa đủ 3s
            thickness = 2
        else:
            color = C_NORMAL_BOX
            thickness = 2

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        # Nền nhãn
        label_text = f"P{pid+1} | {label_vn}"
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
        ov = frame.copy()
        cv2.rectangle(ov, (8, 8), (240, 58), (0, 0, 0), -1)
        cv2.addWeighted(ov, 0.5, frame, 0.5, 0, frame)
        cv2.putText(frame, f"Phat hien: {n_persons} nguoi",
                    (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (200, 255, 200), 1, cv2.LINE_AA)
        if n_alert > 0:
            cv2.putText(frame, f"VI PHAM: {n_alert} nguoi",
                        (14, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.58, C_ALERT_BOX, 2, cv2.LINE_AA)

    # ── API ra ngoài ──────────────────────────────────────────
    def get_snapshot_frame(self):
        return self.last_frame

    def get_result(self):
        """
        Tương thích ngược với code cũ (trả về người đầu tiên vi phạm,
        hoặc người đầu tiên phát hiện).
        Code mới nên dùng self.persons trực tiếp.
        """
        if not self.persons:
            return {
                'pose': 'Khong phat hien', 'confidence': 0.0,
                'is_detected': False, 'hip_norm': None, 'person_bbox': None,
                'persons': {}
            }

        # Ưu tiên người đang vi phạm
        for pid, info in self.persons.items():
            if info.get('is_stooping'):
                return {
                    'pose':        info['pose'],
                    'confidence':  info['confidence'],
                    'is_detected': True,
                    'hip_norm':    info['hip_norm'],
                    'person_bbox': info['bbox'],
                    'persons':     self.persons,
                }

        # Mặc định: người đầu tiên
        first = next(iter(self.persons.values()))
        return {
            'pose':        first['pose'],
            'confidence':  first['confidence'],
            'is_detected': True,
            'hip_norm':    first['hip_norm'],
            'person_bbox': first['bbox'],
            'persons':     self.persons,
        }
