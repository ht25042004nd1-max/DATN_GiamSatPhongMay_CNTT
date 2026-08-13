# ============================================================
# download_model.py — Tải model AI về máy (chạy 1 lần khi cài đặt)
#
# Models cần thiết:
#   1. YOLOv8m-Pose (chính): nhận diện tư thế 17 keypoints COCO
#   2. MediaPipe Pose Lite (fallback): nhận diện tư thế 33 keypoints
#
# Cách chạy:
#   python download_model.py
#
# File được lưu tại thư mục models/ trong thư mục gốc dự án.
# ============================================================
import os
import urllib.request
import sys

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

# ── Model 1: YOLOv8m-Pose (chính) ─────────────────────────
YOLO_MODEL_NAME = "yolov8m-pose.pt"
YOLO_MODEL_PATH = os.path.join(MODEL_DIR, YOLO_MODEL_NAME)

# ── Model 2: MediaPipe Pose Lite (fallback) ────────────────
MP_MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
MP_MODEL_PATH = os.path.join(MODEL_DIR, "pose_landmarker_lite.task")


def _progress(count, block_size, total_size):
    """Callback hiển thị tiến trình tải."""
    if total_size > 0:
        pct = min(count * block_size * 100 // total_size, 100)
        print(f"\r    {pct}% ({count * block_size // 1024} KB / {total_size // 1024} KB)", end="", flush=True)


def download_yolo():
    """
    Tải YOLOv8m-Pose bằng Ultralytics (tự động tải về ~/.ultralytics/assets/).
    Sau đó copy sang thư mục models/ để dùng offline.
    """
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(YOLO_MODEL_PATH):
        size_mb = os.path.getsize(YOLO_MODEL_PATH) / 1024 / 1024
        print(f"[OK] YOLOv8m-Pose da co san: {YOLO_MODEL_PATH} ({size_mb:.1f} MB)")
        return YOLO_MODEL_PATH

    print(f"[*] Dang tai YOLOv8m-Pose qua Ultralytics...")
    print(f"    (File ~52 MB, can ket noi internet lan dau tien)")

    try:
        from ultralytics import YOLO
        # Ultralytics tự tải model nếu chưa có, lưu vào ~/.ultralytics/assets/
        model = YOLO(YOLO_MODEL_NAME)
        print(f"\n    [OK] Ultralytics da tai xong.")

        # Tìm file model đã tải và copy sang models/
        import shutil
        import glob

        # Tìm trong các vị trí phổ biến Ultralytics lưu model
        search_paths = [
            os.path.expanduser(f'~/.ultralytics/assets/{YOLO_MODEL_NAME}'),
            YOLO_MODEL_NAME,   # thư mục hiện tại
            os.path.join(os.path.expanduser('~'), YOLO_MODEL_NAME),
        ]
        # Thêm thư mục Ultralytics mặc định trên Windows
        if sys.platform == 'win32':
            search_paths.append(
                os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Roaming',
                             'ultralytics', 'assets', YOLO_MODEL_NAME)
            )

        copied = False
        for path in search_paths:
            if os.path.exists(path):
                shutil.copy(path, YOLO_MODEL_PATH)
                print(f"    [OK] Da copy model sang: {YOLO_MODEL_PATH}")
                copied = True
                break

        if not copied:
            # Nếu không tìm thấy → lưu thẳng từ YOLO object
            model.save(YOLO_MODEL_PATH)
            print(f"    [OK] Da luu model tai: {YOLO_MODEL_PATH}")

    except ImportError:
        print("[ERROR] Chua cai ultralytics. Chay: pip install ultralytics")
        return None
    except Exception as e:
        print(f"[ERROR] Loi tai YOLOv8m-Pose: {e}")
        return None

    return YOLO_MODEL_PATH


def download_mediapipe():
    """
    Tải model MediaPipe Pose Lite (fallback).
    Dùng urllib trực tiếp từ Google Storage.
    """
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(MP_MODEL_PATH):
        size_kb = os.path.getsize(MP_MODEL_PATH) // 1024
        print(f"[OK] MediaPipe model da co san: {MP_MODEL_PATH} ({size_kb} KB)")
        return MP_MODEL_PATH

    print(f"[*] Dang tai model MediaPipe Pose Lite tu Google Storage...")
    print(f"    URL : {MP_MODEL_URL}")
    print(f"    Luu : {MP_MODEL_PATH}")
    print("    (Khoang 5-10 MB, vui long cho...)")

    try:
        urllib.request.urlretrieve(MP_MODEL_URL, MP_MODEL_PATH, reporthook=_progress)
        print()
        size_kb = os.path.getsize(MP_MODEL_PATH) // 1024
        print(f"[OK] Tai xong! MediaPipe model luu tai: {MP_MODEL_PATH} ({size_kb} KB)")
    except Exception as e:
        print(f"\n[ERROR] Loi tai MediaPipe model: {e}")
        return None

    return MP_MODEL_PATH


if __name__ == "__main__":
    print("=" * 60)
    print("  LabWatch — Tai model AI")
    print("=" * 60)
    print()

    # Tải YOLOv8m-Pose (chính)
    print("--- [1/2] YOLOv8m-Pose (model chinh) ---")
    yolo_path = download_yolo()
    print()

    # Tải MediaPipe (fallback)
    print("--- [2/2] MediaPipe Pose Lite (fallback) ---")
    mp_path = download_mediapipe()
    print()

    print("=" * 60)
    if yolo_path:
        print(f"[OK] YOLOv8m-Pose  : {yolo_path}")
    else:
        print("[WARN] YOLOv8m-Pose : KHONG TAI DUOC — se dung MediaPipe fallback")
    if mp_path:
        print(f"[OK] MediaPipe     : {mp_path}")
    else:
        print("[WARN] MediaPipe   : KHONG TAI DUOC")
    print()
    print("Da san sang! Chay: python run.py")
    print("=" * 60)
