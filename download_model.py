# ============================================================
# download_model.py — Tải model MediaPipe Pose về máy (chạy 1 lần)
#
# MediaPipe >= 0.10 dùng API Tasks mới, cần file model .task riêng.
# Script này tự động tải file đó về thư mục models/
#
# Cách chạy:
#   python download_model.py
# ============================================================
import os
import urllib.request

MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
MODEL_DIR  = os.path.join(os.path.dirname(__file__), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "pose_landmarker_lite.task")


def download():
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(MODEL_PATH):
        size = os.path.getsize(MODEL_PATH)
        print(f"[OK] Model da co san: {MODEL_PATH} ({size // 1024} KB)")
        return MODEL_PATH

    print(f"[*] Dang tai model tu Google MediaPipe...")
    print(f"    URL : {MODEL_URL}")
    print(f"    Luu : {MODEL_PATH}")
    print("    (Khoang 10-30 MB, vui long cho...)")

    def progress(count, block_size, total_size):
        pct = min(count * block_size * 100 // total_size, 100)
        print(f"\r    {pct}% ", end="", flush=True)

    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, reporthook=progress)
    print()
    print(f"[OK] Tai xong! Model luu tai: {MODEL_PATH}")
    return MODEL_PATH


if __name__ == "__main__":
    download()
