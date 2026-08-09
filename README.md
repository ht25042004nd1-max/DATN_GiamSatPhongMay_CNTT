# 🖥️ Hệ Thống Giám Sát An Toàn Phòng Thực Hành Máy Tính (Lab Monitor v2)

> **Đề tài tốt nghiệp** — Ứng dụng Computer Vision (MediaPipe Pose) kết hợp IoT (ESP32) để giám sát và cảnh báo tư thế, hành vi không an toàn trong phòng thực hành máy tính CNTT.

Hệ thống được thiết kế theo phong cách giao diện **Liquid Glass (Kính lỏng)** sang trọng, trôi nổi, hỗ trợ chế độ tối (Dark Mode) và cung cấp trải nghiệm realtime mượt mà.

---

## 📋 Tính Năng Chính Của Hệ Thống

1. **Giám sát Camera Realtime**: Live-stream MJPEG từ Camera với skeleton (khung xương cơ thể) vẽ đè lên hình ảnh. Tự động lặp video test `sample.mp4` nếu không có webcam.
2. **Nhận Diện Tư Thế Bằng AI (MediaPipe Pose)**: Phân loại tư thế Đứng, Cúi người, Ngồi, Quỳ dựa trên tính toán góc hình học (Vai-Hông-Gối) bằng NumPy kết hợp thuật toán làm mượt qua 5 frame liên tiếp để chống nhiễu.
3. **Quản Lý Vùng ROI (Region of Interest)**: Vẽ các vùng đa giác (Polygon) trực quan bằng chuột trực tiếp trên khung hình camera. Hỗ trợ bật/tắt, sửa/xóa và phân mức độ nghiêm trọng (Thấp, Trung bình, Cao) cho từng ROI.
4. **Engine Phân Tích & Kích Hoạt Cảnh Báo**:
   - Điều kiện vi phạm: Người nằm trong ROI **AND** có tư thế vi phạm (`Cúi`, `Ngồi`, `Quỳ`) **AND** duy trì thời gian $\ge$ X giây.
   - Cơ chế cooldown 60 giây chống spam tin nhắn.
   - Gộp nhiều người vi phạm đồng thời trên cùng khung hình thành một sự kiện duy nhất.
5. **Cảnh Báo Telegram Realtime**: Tự động gửi thông tin vi phạm (Thời gian, ROI, Tư thế, Mã sự kiện) kèm ảnh chụp minh chứng lúc vi phạm qua Telegram Bot. Hỗ trợ cấu hình khung giờ hoạt động của Bot.
6. **Tích Hợp Điều Khiển Thiết Bị IoT (ESP32)**:
   - Điều khiển Đèn LED, Relay, Còi buzzer cảnh báo tại phòng máy qua HTTP REST API.
   - Theo dõi trạng thái Online/Offline của ESP32 qua cơ chế Heartbeat định kỳ mỗi 10 giây.
   - Tích hợp sẵn bộ giả lập (Mock ESP32) chạy ngầm trực quan đổi trạng thái đèn/còi trên web.
7. **Thống Kê Trực Quan & Xuất Báo Cáo PDF**:
   - Thống kê các KPI và hiển thị biểu đồ phân tích (Line, Bar, Doughnut, Horizontal Bar) bằng Chart.js.
   - Xuất báo cáo PDF tiếng Việt có dấu (sử dụng thư viện ReportLab kết hợp Arial Unicode) bao gồm số liệu, biểu đồ và Album ảnh minh chứng của các ca vi phạm nghiêm trọng.
8. **Quản Lý Tài Khoản (CRUD)**: Quản trị viên (Admin) quản lý danh sách giám sát viên, reset mật khẩu và mở khóa tài khoản khi bị khóa tạm (sau 5 lần nhập sai mật khẩu liên tiếp).

---

## 🛠️ Công Nghệ Sử Dụng (Tech Stack)

* **Backend**: Python 3.11, Flask
* **Database**: SQLite (SQLAlchemy ORM)
* **Trí Tuệ Nhân Tạo & Thị Giác Máy Tính**: MediaPipe Pose, OpenCV, NumPy
* **Frontend**: HTML5, Vanilla CSS (Liquid Glass System), JavaScript (Chart.js qua CDN)
* **Giao Thức IoT**: HTTP REST API + Heartbeats (JSON)
* **Thư Viện PDF**: ReportLab + Pillow
* **Môi Trường Đóng Gói**: Docker & Docker Compose

---

## 🚀 Hướng Dẫn Cài Đặt Và Chạy Hệ Thống

Dự án hỗ trợ 2 phương pháp khởi chạy: Chạy trực tiếp bằng Python (Local) hoặc Chạy tự động thông qua Docker.

### Cách 1: Chạy Bằng Docker & Docker Compose (Khuyên dùng khi demo)

Yêu cầu máy tính đã cài đặt **Docker Desktop** (Tải tại [docker.com](https://www.docker.com/)).

1. **Khởi động toàn bộ hệ thống bằng 1 lệnh duy nhất**:
   ```bash
   docker-compose up --build -d
   ```
2. **Tạo tài khoản Admin mặc định** (chạy lần đầu):
   ```bash
   docker exec -it lab_monitor_web python create_admin.py
   ```
3. **Mở trình duyệt truy cập**: `http://localhost:5000`
   - Tài khoản đăng nhập mặc định:
     - Tên đăng nhập: `admin`
     - Mật khẩu: `admin123`
4. **Dữ liệu được lưu trữ an toàn** tại thư mục `./database` và `./static/uploads` trên máy thật của bạn nhờ cơ chế Volume Mount.

---

### Cách 2: Cài Đặt Thủ Công Trên Máy Tính (Local)

Yêu cầu máy tính cài đặt **Python 3.10 hoặc 3.11**.

1. **Tạo môi trường ảo (venv) và kích hoạt**:
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate
   ```
2. **Cài đặt các thư viện**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Tải model AI MediaPipe**:
   ```bash
   python download_model.py
   ```
4. **Tạo file cấu hình `.env`**:
   Sao chép `.env.example` thành `.env` và cập nhật thông tin:
   ```env
   SECRET_KEY=chuoi-bi-mat-cua-ban
   CAMERA_SOURCE=0
   ```
5. **Khởi tạo cơ sở dữ liệu và tài khoản Admin**:
   ```bash
   python create_admin.py
   ```
6. **Khởi chạy ứng dụng**:
   ```bash
   python run.py
   ```
   Mở trình duyệt truy cập `http://127.0.0.1:5000`.

---

## 🔌 Cấu Hình Telegram Bot và Thiết Bị IoT (ESP32)

### A. Cấu Hình Telegram Bot
1. Truy cập Telegram, tìm kiếm `@BotFather`, gõ `/newbot` để tạo bot mới và nhận **Bot Token**.
2. Tìm kiếm `@userinfobot` (hoặc add bot của bạn vào group, sau đó lấy Chat ID của group qua url `https://api.telegram.org/bot<Token>/getUpdates`).
3. Đăng nhập vào hệ thống Lab Monitor bằng quyền Admin, truy cập trang **Quản trị -> Cấu hình**, nhập Bot Token và Chat ID. Nhấn **Kiểm tra kết nối** để xác nhận thành công trước khi bật.

### B. Chuyển Từ ESP32 Giả Lập Sang ESP32 Thiết Bị Thật
Hệ thống mặc định sử dụng IP giả lập nội bộ `/mock_esp32` để mô phỏng trạng thái đèn LED và còi kêu trực tiếp trên giao diện web. Khi chuyển sang phần cứng thật:

1. **Chuẩn bị phần cứng**:
   - 1 Board mạch ESP32 NodeMCU.
   - 1 Đèn LED (nối chân GPIO 2).
   - 1 Còi Buzzer chủ động (nối chân GPIO 4).
   - 1 Module Relay 5V kích mức thấp/cao (nối chân GPIO 5).
2. **Nạp Firmware**:
   - Mở mã nguồn trong thư mục [firmware/esp32_firmware.ino](file:///d:/Documents/DATN/DATN_GiamSatPhongMay_CNTT/firmware/esp32_firmware.ino) bằng phần mềm **Arduino IDE**.
   - Cấu hình Tên Wifi (`ssid`), Mật khẩu (`password`) và Địa chỉ IP của Flask server (`host` - máy tính chạy web app).
   - Nạp chương trình lên board ESP32.
3. **Thay Đổi Cấu Hình Trên Web**:
   - Khi ESP32 khởi động, nó sẽ kết nối Wifi và tự động gửi thông tin Heartbeat kèm địa chỉ IP của nó lên server.
   - Đăng nhập web app bằng quyền Admin, vào mục **Quản trị -> Cấu hình**.
   - Thay đổi ô **IP Thiết bị ESP32** thành địa chỉ IP thật của ESP32 hiển thị trên màn hình Serial monitor của Arduino IDE (ví dụ: `http://192.168.1.50`).
   - Nhấn **Lưu cấu hình**.
   - Truy cập trang **Quản trị -> Thiết bị IoT** để xem trạng thái ESP32 thật đã chuyển sang "Online" và bấm nút điều khiển test thủ công còi/đèn.

---

## 📁 Cấu Trúc Mã Nguồn

```
DATN_GiamSatPhongMay_CNTT/
│
├── app/                        # Mã nguồn ứng dụng Python/Flask
│   ├── models/                 # Các thực thể CSDL (User, Event, ROI, Setting)
│   ├── routes/                 # Xử lý các đường dẫn API và trang view HTML
│   │   ├── auth.py             # Route đăng nhập/đăng xuất/xác thực
│   │   ├── main.py             # Route chính & API CRUD quản lý tài khoản
│   │   ├── settings_routes.py  # API cấu hình hệ thống
│   │   ├── iot_routes.py       # API nhận Heartbeat & Giả lập ESP32
│   │   ├── roi_routes.py       # API quản lý và lưu vùng ROI
│   │   ├── statistics_routes.py# API tổng hợp dữ liệu thống kê vẽ biểu đồ
│   │   └── reports_routes.py   # API ReportLab sinh và xuất báo cáo PDF
│   │
│   ├── services/               # Các dịch vụ xử lý logic nghiệp vụ ngầm
│   │   ├── camera_service.py   # Đọc camera, tích hợp AI và quản lý stream
│   │   ├── pose_analyzer.py    # MediaPipe phân tích tọa độ & tính toán góc
│   │   ├── alert_engine.py     # Đánh giá vi phạm (Ray Casting), tạo sự kiện
│   │   ├── telegram_service.py # Xử lý gửi tin nhắn, ảnh và kiểm tra kết nối
│   │   └── esp32_service.py    # Gửi lệnh điều khiển phần cứng & Heartbeats
│   │
│   └── utils/                  # Các decorator quyền hạn người dùng
│
├── firmware/                   # Code nạp cho board mạch ESP32
│   └── esp32_firmware.ino
│
├── database/                   # Chứa tệp tin cơ sở dữ liệu SQLite
├── static/                     # Các tài nguyên tĩnh (CSS, JS, Hình ảnh, Font)
├── templates/                  # Các giao diện HTML dùng cú pháp Jinja2
├── Dockerfile                  # Cấu hình build Docker image
├── docker-compose.yml          # Cấu hình khởi chạy hệ thống bằng Docker
├── create_admin.py             # Script tạo nhanh tài khoản Admin mặc định
├── download_model.py           # Script tải trước model MediaPipe Pose
├── requirements.txt            # Danh sách thư viện Python cần cài đặt
└── README.md                   # Tài liệu này
```

---

## 🔮 Hướng Phát Triển Trong Tương Lai (Ghi chú báo cáo)

Nếu được hỏi về các điểm hạn chế hoặc hướng nâng cấp hệ thống trong tương lai trước hội đồng phản biện, bạn có thể trình bày các hướng phát triển sau:

1. **Mở Rộng Hệ Thống Multi-camera (Đa kênh)**:
   - *Hạn chế hiện tại*: Phiên bản thử nghiệm tối ưu hóa xử lý mượt mà trên 1 luồng camera chính (với MediaPipe Pose chạy trên CPU).
   - *Giải pháp tương lai*: Chuyển đổi công nghệ nhận diện pose sang các framework tối ưu hơn như **YOLOv8-Pose** chạy trên GPU chuyên dụng, hỗ trợ xử lý luồng đồng thời từ nhiều camera IP RTSP khác nhau trong phòng máy.
2. **Nhận Diện Danh Tính Học Sinh (Face Recognition)**:
   - *Hạn chế hiện tại*: Hệ thống phát hiện vi phạm tư thế ngồi sai của cơ thể người nói chung nhưng chưa định danh chính xác học sinh đó là ai trong lớp.
   - *Giải pháp tương lai*: Tích hợp thêm module nhận dạng khuôn mặt (FaceID) tại bàn giáo viên để điểm danh và đối chiếu vị trí học sinh ngồi vi phạm nhằm ghi nhận tự động vào điểm chuyên cần của môn học.
3. **Phân Tích Hành Vi Phức Tạp Bằng Trí Tuệ Nhân Tạo**:
   - *Hạn chế hiện tại*: Mới chỉ nhận diện các tư thế tĩnh có sẵn (Cúi, Ngồi, Quỳ) dựa trên góc vai-hông-gối của 1 frame.
   - *Giải pháp tương lai*: Áp dụng mạng neuron tuần hoàn **LSTM** hoặc mô hình **GCN (Graph Convolutional Networks)** phân tích chuỗi các frame liên tiếp nhằm phát hiện các hành vi động phức tạp hơn như: đùa nghịch, xô đẩy nhau trong phòng máy hoặc phá hoại thiết bị.
#   D A T N _ G i a m S a t P h o n g M a y _ C N T T  
 