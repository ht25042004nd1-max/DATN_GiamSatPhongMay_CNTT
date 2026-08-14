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

def start_background_services():
    """Khởi động các dịch vụ nền (AI Camera và Telegram Bot)"""
    print("[*] Dang khoi dong AI Camera ngam...")
    with app.app_context():
        try:
            from app.models.camera import Camera
            from app.services.camera_service import camera_manager
            
            cameras = Camera.query.filter_by(is_active=True).all()
            for cam in cameras:
                # Không tự động bật Client Camera vì cần client chủ động gửi frame
                if cam.rtsp_url and str(cam.rtsp_url).lower() != 'client_camera':
                    print(f"    - Khoi dong Camera #{cam.id}: {cam.name}")
                    source = int(cam.rtsp_url) if cam.rtsp_url.isdigit() else cam.rtsp_url
                    # Khởi tạo camera để stream xử lý ngầm (web recognition)
                    camera_manager.get_camera(cam.id, source=source)
        except Exception as e:
            print(f"[!] Loi khoi dong AI Camera: {e}")

    print("[*] Dang khoi dong Telegram Bot...")
    try:
        import telegram_bot
        # telegram_bot.py có tự động gọi start_bot_polling() khi import
    except Exception as e:
        print(f"[!] Loi khoi dong Telegram Bot: {e}")

if __name__ == '__main__':
    # Render và các dịch vụ cloud khác tự động cấp một biến môi trường tên là PORT
    port = int(os.getenv('PORT', os.getenv('FLASK_PORT', 5000)))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

    # Chỉ chạy service nền 1 lần duy nhất (tránh duplicate khi Flask auto-reload)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not debug:
        start_background_services()

    print("[*] Khoi dong server tai http://localhost:{}".format(port))
    print("    Che do debug: {}".format(debug))
    print("    Nhan Ctrl+C de dung server")

    app.run(host='0.0.0.0', port=port, debug=debug)
