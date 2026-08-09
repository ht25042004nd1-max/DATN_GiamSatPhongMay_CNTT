# ============================================================
# run.py — Điểm khởi động chính của ứng dụng Flask
# Chạy file này để start server: python run.py
# ============================================================
import os
import sys

from dotenv import load_dotenv

# Tải biến môi trường từ file .env
load_dotenv()

from app import create_app

# Tạo instance ứng dụng Flask
app = create_app()

if __name__ == '__main__':
    # Render và các dịch vụ cloud khác tự động cấp một biến môi trường tên là PORT
    port = int(os.getenv('PORT', os.getenv('FLASK_PORT', 5000)))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

    print("[*] Khoi dong server tai http://localhost:{}".format(port))
    print("    Che do debug: {}".format(debug))
    print("    Nhan Ctrl+C de dung server")

    app.run(host='0.0.0.0', port=port, debug=debug)
