import cv2
import time

# HƯỚNG DẪN ĐIỀN THÔNG TIN:
# 1. Thay "admin" bằng user mặc định (thường là admin)
# 2. Thay "ABCDEF" bằng MÃ VERIFICATION CODE (in dưới đít camera EZVIZ, gồm 6 chữ cái viết hoa)
# 3. Thay "192.168.1.100" bằng địa chỉ IP tĩnh của camera trong mạng Wifi nhà bạn

RTSP_URL = "rtsp://admin:ABCDEF@192.168.1.100:554/h264_stream"

print(f"Đang thử kết nối tới luồng RTSP: {RTSP_URL}")
print("Vui lòng đợi vài giây...")

cap = cv2.VideoCapture(RTSP_URL)

if not cap.isOpened():
    print("❌ KHÔNG THỂ KẾT NỐI! Hãy kiểm tra lại IP, mã Verification Code hoặc xem camera có cùng mạng Wifi với máy tính không.")
else:
    print("✅ KẾT NỐI THÀNH CÔNG! Đang hiển thị hình ảnh (Nhấn 'q' để thoát)...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ Luồng video bị ngắt.")
            break
            
        cv2.imshow("Test Camera EZVIZ", frame)
        
        # Nhấn phím 'q' để thoát
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
