# ============================================================
# app/services/camera_service.py — Module quản lý camera / video stream
# (Cập nhật Giai đoạn 3: tích hợp MediaPipe Pose Analyzer)
#
# Pipeline xử lý mỗi frame:
#   Đọc frame từ webcam/video
#     → PoseAnalyzer.process_frame() (MediaPipe + vẽ skeleton)
#     → Encode JPEG
#     → Stream qua HTTP MJPEG
# ============================================================
import cv2
import os
import time
import threading
import numpy as np
from datetime import datetime


class CameraService:
    """
    Singleton quản lý luồng camera + tích hợp AI pose detection.
    Chạy trong thread riêng để không chặn Flask.
    """

    def __init__(self):
        self.cap          = None
        self.frame        = None          # Frame gốc (chưa xử lý AI)
        self.processed    = None          # Frame đã vẽ skeleton
        self.lock         = threading.Lock()
        self.running      = False
        self.fps          = 0.0
        self.source_name  = "Khong xac dinh"
        self.is_online    = False
        self._thread      = None

        # AI Pose Analyzer (khởi tạo lazy khi camera bắt đầu)
        self._pose        = None
        self.pose_enabled = False         # Bật/tắt AI processing
        self.pose_result  = {             # Kết quả pose mới nhất
            "pose":        "Khong phat hien",
            "confidence":  0.0,
            "is_detected": False,
        }

        # Benchmarks & Stability metrics (Giai đoạn 5 Tuần 13)
        self.total_frames   = 0
        self.dropped_frames = 0
        self.start_time     = time.time()

    # ─── Khởi động camera ──────────────────────────────────
    def start(self, source=0, fallback_video=None, enable_pose=True):
        """
        Khởi động luồng đọc camera.
        - source:        index webcam hoặc đường dẫn video
        - fallback_video: file .mp4 dự phòng
        - enable_pose:   True = bật MediaPipe AI
        """
        if self.running:
            return

        # Khởi tạo PoseAnalyzer
        if enable_pose:
            try:
                from app.services.pose_analyzer import PoseAnalyzer
                self._pose = PoseAnalyzer()
                self.pose_enabled = True
                print("[Camera] MediaPipe Pose: DA BAT")
            except Exception as e:
                print(f"[Camera] MediaPipe khoi tao that bai: {e}")
                self.pose_enabled = False

        # Chạy toàn bộ việc mở camera trong background thread để không block HTTP request
        self.running = True
        self.source_name = "Đang kết nối..."
        self._thread = threading.Thread(
            target=self._init_and_run,
            args=(source, fallback_video),
            daemon=True
        )
        self._thread.start()
        print(f"[Camera] Dang khoi dong camera (background)...")

    def _init_and_run(self, source, fallback_video):
        """Chạy trong background thread: thử mở camera rồi vào vòng lặp đọc frame."""
        opened = self._try_open(source)

        if not opened and fallback_video and os.path.exists(fallback_video):
            print(f"[Camera] Webcam khong mo duoc, dung video: {fallback_video}")
            opened = self._try_open(fallback_video)
            if opened:
                self.source_name = f"Video: {os.path.basename(fallback_video)}"

        if not opened:
            print("[Camera] Khong tim thay nguon video — Offline mode.")
            self.is_online   = False
            self.source_name = "Offline"
            self._loop_offline()
        else:
            self.is_online = True
            print(f"[Camera] Nguon: {self.source_name} | Online: {self.is_online} | AI: {self.pose_enabled}")
            self._loop_read()

    def _try_open(self, source):
        # CAP_DSHOW chỉ có trên Windows; trên Linux (Render) phải dùng backend mặc định
        import platform
        is_win = platform.system() == 'Windows'

        if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
            src_int = int(source)
            if is_win:
                cap = cv2.VideoCapture(src_int, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(src_int)
        else:
            # IP Camera, RTSP, hoặc đường dẫn video file
            src_str = str(source).strip()
            # Thêm timeout: rtsp_transport;tcp cho ổn định, timeout 5s (5,000,000 us)
            if src_str.lower().startswith('rtsp://'):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000000"
            else:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;5000000"
            cap = cv2.VideoCapture(src_str)

        if cap.isOpened():
            self.cap = cap
            if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
                # Tối ưu cài đặt camera: chất lượng cao + giảm buffer lag
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)
                cap.set(cv2.CAP_PROP_FPS,           30)
                cap.set(cv2.CAP_PROP_BUFFERSIZE,     2)   # giảm buffer lag
                cap.set(cv2.CAP_PROP_AUTOFOCUS,      1)   # tự động lấy nét
                self.source_name = f"Webcam #{source}"
            else:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Giảm lag tối đa cho IP stream
                if str(source).startswith(('http://', 'https://')):
                    self.source_name = f"IP Camera ({source})"
                elif str(source).startswith('rtsp://'):
                    self.source_name = f"RTSP Stream ({source})"
                else:
                    self.source_name = f"Video: {os.path.basename(str(source))}"
            return True
        cap.release()
        return False

    # ─── Vòng lặp đọc frame ────────────────────────────────
    def _loop_read(self):
        """Thread chính: đọc frame → xử lý AI → lưu vào bộ nhớ."""
        t_prev     = time.time()
        frame_cnt  = 0
        consecutive_failures = 0

        try:
            while self.running:
                if self.cap is None or not self.cap.isOpened():
                    break
                ret, frame = self.cap.read()

                if not ret:
                    self.dropped_frames += 1
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        print("[Camera] Mất kết nối camera liên tục. Chuyển sang Offline mode.")
                        self.is_online = False
                        self.source_name = "Offline"
                        if self.cap:
                            self.cap.release()
                        self._loop_offline()
                        break
                    
                    # Thử tua lại video (nếu là file)
                    try:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass
                    time.sleep(0.1)
                    continue

                # ── Frame Pacing (25-30 FPS) & Stale Buffer Flush ──
                t_frame_start = time.time()
                
                # Nếu là luồng RTSP / IP camera: grab bỏ các frame cũ dồn trong buffer
                if hasattr(self, 'source_name') and ("RTSP" in self.source_name or "IP" in self.source_name):
                    # Flush tối đa 2 frame đệm để giữ real-time latency
                    for _ in range(2):
                        if not self.cap.grab():
                            break

                self.total_frames += 1
                consecutive_failures = 0

                frame_cnt += 1
                t_now = time.time()
                if t_now - t_prev >= 1.0:
                    self.fps   = round(frame_cnt / (t_now - t_prev), 1)
                    frame_cnt  = 0
                    t_prev     = t_now

                # ── Xử lý AI Pose trên frame (15 FPS với FRAME_SKIP = 2) ──
                FRAME_SKIP = 2
                should_run_ai = (self.total_frames % FRAME_SKIP == 0)

                if self.pose_enabled and self._pose:
                    if should_run_ai or not hasattr(self, '_last_ai_processed') or self._last_ai_processed is None:
                        try:
                            processed = self._pose.process_frame(frame.copy())
                            result    = self._pose.get_result()   # {pose, confidence, persons, ...}
                            self._last_ai_processed = processed
                            self._last_ai_result    = result
                        except Exception:
                            processed = frame.copy()
                            result = {"pose": "AI error", "confidence": 0.0, "is_detected": False, "persons": {}}
                    else:
                        processed = self._last_ai_processed
                        result    = getattr(self, '_last_ai_result', {"pose": "Chờ", "confidence": 0.0, "is_detected": False, "persons": {}})

                    # ── Gửi kết quả sang AlertEngine khi có kết quả AI mới ──
                    if should_run_ai:
                        try:
                            from app.services.alert_engine import alert_engine
                            hip_norm = result.get('hip_norm')
                            alert_engine.process_frame(result, hip_norm)
                        except Exception:
                            pass
                else:
                    processed = frame.copy()
                    result    = {"pose": "AI off", "confidence": 0.0,
                                 "is_detected": False, "persons": {}}

                with self.lock:
                    self.frame       = frame
                    self.processed   = processed
                    self.pose_result = result

                # Điều tiết tốc độ đọc frame khoảng 30 FPS (mỗi frame ~33.3ms)
                TARGET_FRAME_TIME = 1.0 / 30.0  # 30 FPS target
                elapsed = time.time() - t_frame_start
                if elapsed < TARGET_FRAME_TIME:
                    time.sleep(TARGET_FRAME_TIME - elapsed)
                else:
                    time.sleep(0.001)
        except Exception as e:
            print(f"[Camera] Thread _loop_read ket thuc an toan: {e}")
        finally:
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass

    def _loop_offline(self):
        """Thread tạo frame đen khi không có camera."""
        while self.running:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            text = "Camera Offline"
            font = cv2.FONT_HERSHEY_SIMPLEX
            sz, _ = cv2.getTextSize(text, font, 1.5, 2)
            x = (1280 - sz[0]) // 2
            y = (720  + sz[1]) // 2
            cv2.putText(frame, text, (x, y), font, 1.5, (80, 80, 80), 2)
            with self.lock:
                self.frame     = frame
                self.processed = frame
            self.fps = 0.0
            time.sleep(0.5)

    # ─── Dừng ───────────────────────────────────────────────
    def stop(self):
        self.running = False

    def capture_snapshot(self, event_id: int = None, save_dir: str = None) -> bytes:
        """
        Chụp và lưu ảnh minh chứng chất lượng cao (kèm khung đỏ cảnh báo & skeleton).
        
        Args:
            event_id: ID sự kiện để đặt tên file (VD: 42.jpg)
            save_dir:  Thư mục lưu, mặc định app/static/uploads/events/
        
        Returns:
            bytes: Nội dung JPEG của frame, hoặc ảnh đen nếu camera offline.
        """
        with self.lock:
            # Ưu tiên frame đã xử lý AI (có skeleton + Bounding Box đỏ vi phạm để làm bằng chứng gửi Telegram)
            src = self.processed if self.processed is not None else self.frame
            if src is None:
                src = np.zeros((720, 1280, 3), dtype=np.uint8)
            snap = src.copy()

        # Vẽ watermark thời gian lên ảnh
        ts_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        h, w = snap.shape[:2]
        # Nền bán trong suốt phía dưới
        overlay = snap.copy()
        cv2.rectangle(overlay, (0, h - 36), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, snap, 0.45, 0, snap)
        cv2.putText(snap, f"VIU Lab Monitor | {ts_str}",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (200, 200, 200), 1, cv2.LINE_AA)

        # Encode JPEG chất lượng cao
        _, buf = cv2.imencode('.jpg', snap, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_bytes = buf.tobytes()

        # Lưu file
        try:
            from flask import current_app
            base_dir = save_dir or os.path.join(
                current_app.static_folder, 'uploads', 'events')
        except RuntimeError:
            base_dir = save_dir or os.path.join('app', 'static', 'uploads', 'events')

        os.makedirs(base_dir, exist_ok=True)

        if event_id is not None:
            filename = f"{event_id}.jpg"
        else:
            filename = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

        try:
            filepath = os.path.join(base_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(img_bytes)
            self._last_snapshot_path = filepath
        except Exception as e:
            print(f"[Camera] Loi luu snapshot: {e}")

        return img_bytes

    def get_frame(self):
        """
        Trả về frame đã xử lý AI (có skeleton) dạng bytes JPEG.
        Nếu AI tắt, trả về frame gốc.
        """
        with self.lock:
            src = self.processed if self.processed is not None else self.frame
            if src is None:
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                _, buf = cv2.imencode('.jpg', blank)
                return buf.tobytes()
            _, buf = cv2.imencode('.jpg', src, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return buf.tobytes()

    def get_status(self):
        """Trả về dict trạng thái camera + kết quả pose."""
        with self.lock:
            pose = dict(self.pose_result)  # copy tránh race condition
        uptime_sec = int(time.time() - self.start_time)
        drop_rate = round((self.dropped_frames / self.total_frames * 100), 2) if self.total_frames > 0 else 0.0
        return {
            'source_name':    self.source_name,
            'fps':            self.fps,
            'is_online':      self.is_online,
            'timestamp':      datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'pose_enabled':   self.pose_enabled,
            'pose':           pose,
            'total_frames':   self.total_frames,
            'dropped_frames': self.dropped_frames,
            'drop_rate':      drop_rate,
            'uptime_sec':     uptime_sec
        }


class ClientCamera(CameraService):
    """Camera ảo nhận luồng frame từ phía client (trình duyệt) thông qua API."""
    def __init__(self):
        super().__init__()
        self.new_frame_event = threading.Event()

    def start(self, source=0, fallback_video=None, enable_pose=True):
        if self.running:
            return

        if enable_pose:
            try:
                from app.services.pose_analyzer import PoseAnalyzer
                self._pose = PoseAnalyzer()
                self.pose_enabled = True
                print("[ClientCamera] MediaPipe Pose: DA BAT")
            except Exception as e:
                print(f"[ClientCamera] MediaPipe khoi tao that bai: {e}")
                self.pose_enabled = False

        self.is_online = True
        self.source_name = "Thiết bị Client (Điện thoại/Laptop)"
        self.running = True
        self._thread = threading.Thread(target=self._loop_client, daemon=True)
        self._thread.start()
        print(f"[ClientCamera] Da khoi dong. Cho du lieu tu client.")

    def update_frame(self, frame_bgr):
        """Hàm này được gọi từ API khi có frame gửi lên."""
        with self.lock:
            self.frame = frame_bgr
        self.new_frame_event.set()

    def _loop_client(self):
        t_prev = time.time()
        frame_cnt = 0
        while self.running:
            if not self.new_frame_event.wait(timeout=2.0):
                self.fps = 0.0
                continue
            
            self.new_frame_event.clear()
            
            with self.lock:
                frame = self.frame.copy() if self.frame is not None else None
                
            if frame is None:
                continue

            frame_cnt += 1
            t_now = time.time()
            if t_now - t_prev >= 1.0:
                self.fps = round(frame_cnt / (t_now - t_prev), 1)
                frame_cnt = 0
                t_prev = t_now

            # Xử lý AI Pose trên frame
            if self.pose_enabled and self._pose:
                try:
                    processed = self._pose.process_frame(frame.copy())
                    result = self._pose.get_result()
                except Exception as pose_err:
                    processed = frame.copy()
                    result = {"pose": "AI error", "confidence": 0.0, "is_detected": False, "persons": {}}

                try:
                    from app.services.alert_engine import alert_engine
                    hip_norm = result.get('hip_norm')
                    alert_engine.process_frame(result, hip_norm)
                except Exception:
                    pass
            else:
                processed = frame.copy()
                result = {"pose": "AI off", "confidence": 0.0,
                          "is_detected": False, "persons": {}}

            with self.lock:
                self.processed = processed
                self.pose_result = result



class CameraManager:
    """Quản lý nhiều luồng camera cùng lúc (tránh rò rỉ bộ nhớ)."""
    def __init__(self):
        self._cameras = {}
        self._lock = threading.Lock()
        
    def get_camera(self, camera_id, source=0, fallback_video=None, enable_pose=True):
        with self._lock:
            existing = self._cameras.get(camera_id)
            need_restart = False
            if existing:
                is_client = isinstance(existing, ClientCamera)
                want_client = str(source).lower() == 'client_camera'
                if is_client != want_client:
                    need_restart = True
                elif not is_client and getattr(existing, 'current_source', None) != str(source):
                    need_restart = True

                if need_restart:
                    existing.stop()
                    del self._cameras[camera_id]

            if camera_id not in self._cameras:
                if str(source).lower() == 'client_camera':
                    cam_service = ClientCamera()
                else:
                    cam_service = CameraService()
                cam_service.current_source = str(source)
                cam_service.start(source=source, fallback_video=fallback_video, enable_pose=enable_pose)
                self._cameras[camera_id] = cam_service
            return self._cameras[camera_id]
            
    def remove_camera(self, camera_id):
        with self._lock:
            if camera_id in self._cameras:
                self._cameras[camera_id].stop()
                del self._cameras[camera_id]

    def get_all_stats(self):
        with self._lock:
            total_active = len(self._cameras)
            total_frames = sum(c.total_frames for c in self._cameras.values())
            dropped_frames = sum(c.dropped_frames for c in self._cameras.values())
            avg_fps = round(sum(c.fps for c in self._cameras.values()) / total_active, 1) if total_active > 0 else 0.0
            drop_rate = round((dropped_frames / total_frames * 100), 2) if total_frames > 0 else 0.0
            return {
                'active_cameras': total_active,
                'total_frames': total_frames,
                'dropped_frames': dropped_frames,
                'drop_rate': drop_rate,
                'avg_fps': avg_fps
            }

camera_manager = CameraManager()

