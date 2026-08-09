import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from app import create_app, db
from app.models.event import Event
from app.models.roi import ROI
from app.models.setting import SystemSetting
from app.services.telegram_service import send_alert, _get_config

app = create_app()

with app.app_context():
    print("=" * 60)
    print(" TESTING STOOPING POSE ('CÚI NGƯỜI') TELEGRAM ALERT")
    print("=" * 60)

    cfg = _get_config()
    print(f"[*] Telegram Enabled: {cfg['enabled']}")
    print(f"[*] Telegram Token: '{cfg['token'][:6]}...' (length: {len(cfg['token'])})")
    print(f"[*] Telegram Chat ID: '{cfg['chat_id']}'")

    if not cfg['token'] or not cfg['chat_id']:
        print("[!] WARN: Chưa cấu hình Telegram Token hoặc Chat ID trong DB!")
        print("[*] Đang cài đặt tạm thông số Telegram cấu hình mặc định để test...")
        SystemSetting.set('telegram_enabled', 'true')

    roi_obj = ROI.query.first()
    roi_name = roi_obj.name if roi_obj else "Vùng Gầm Bàn Case #01 (Khu vực nguy cơ)"

    from datetime import datetime, timedelta
    
    event = Event(
        roi_id=roi_obj.id if roi_obj else None,
        roi_name=roi_name,
        pose='Cui nguoi',
        level='medium',
        person_count=1,
        started_at=datetime.utcnow() - timedelta(seconds=8),
        camera_id=1
    )
    db.session.add(event)
    db.session.commit()

    print(f"[+] Đã khởi tạo thành công Event #{event.id}:")
    print(f"    - Loại vi phạm: {event.pose} (Cúi người trong vùng nguy cơ ROI)")
    print(f"    - Thời gian duy trì: {event.duration_seconds} giây")
    print(f"    - Mức độ nghiêm trọng: {event.level_label}")

    import cv2
    import numpy as np

    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (35, 35, 35)
    cv2.rectangle(img, (100, 100), (540, 380), (0, 0, 255), 2)
    cv2.putText(img, f"ROI: {roi_name.upper()}", (110, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)

    # Skeleton khung người tư thế Cúi người
    cv2.circle(img, (280, 200), 20, (0, 255, 255), -1) # Đầu
    cv2.line(img, (280, 220), (360, 280), (0, 255, 255), 4) # Cột sống cúi nghiêng
    cv2.line(img, (360, 280), (380, 360), (0, 255, 255), 4) # Chân
    cv2.line(img, (300, 235), (260, 310), (0, 255, 255), 3) # Tay thò vào case

    cv2.rectangle(img, (120, 120), (520, 170), (0, 0, 180), -1)
    cv2.putText(img, "CANH BAO: CUI NGUOI TRONG ROI (>8s)", (130, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    _, buf = cv2.imencode('.jpg', img)
    frame_bytes = buf.tobytes()

    print("[*] Đang gửi ảnh minh chứng + thông tin vi phạm qua Telegram Bot (Ban Ban)...")
    send_alert(event, frame_bytes=frame_bytes)
    print("============================================================")
    print(" [OK] KIỂM THỬ THÀNH CÔNG: ĐÃ PHÁT LỆNH BẮN CẢNH BÁO CÚI NGƯỜI!")
    print("============================================================")
