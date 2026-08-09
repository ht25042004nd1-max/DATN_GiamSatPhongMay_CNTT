# BÁO CÁO TỔNG QUAN HỆ THỐNG GIÁM SÁT PHÒNG MÁY CNTT (VIU LAB MONITOR)

**Đồ án Tốt nghiệp CNTT:** Ứng dụng Thị giác Máy tính (Computer Vision) và Internet of Things (IoT) trong Giám sát An toàn Phòng Thực hành Máy tính  
**Đơn vị thực hiện:** Trường Đại học Công nghiệp Việt-Hưng (VIU)  
**Ngày cập nhật báo cáo:** 30/07/2026  

---

## I. TỔNG QUAN HỆ THỐNG

**VIU Lab Monitor** là một hệ thống giám sát an toàn và quản lý vận hành phòng thực hành máy tính toàn diện, kết hợp các công nghệ hiện đại:
- **Thị giác Máy tính & AI:** Sử dụng thư viện MediaPipe Pose để nhận diện thời gian thực các tư thế cơ thể người (Đứng, Ngồi, Cúi người, Quỳ gầm bàn) từ luồng Camera/RTSP.
- **Vùng quan sát ROI (Region of Interest):** Cho phép vẽ động các vùng nguy cơ (xung quanh case máy tính, gầm bàn, tủ điện) và kiểm tra sự hiện diện của con người bằng thuật toán Point-in-Polygon (Ray Casting).
- **Cảnh báo Tự động & Telegram Bot "Ban Ban":** Tự động phát hiện vi phạm kéo dài quá ngưỡng thời gian cấu hình, chụp frame ảnh minh chứng, khoanh đỏ khu vực vi phạm và gửi tức thì qua ứng dụng Telegram.
- **Internet of Things (IoT Gateway ESP32):** Kết nối điều khiển còi báo động, đèn LED, relay và thu thập chỉ số môi trường (Nhiệt độ, Độ ẩm, Cảm biến Khói/Gas, Trạng thái Cửa). Tự động báo động khi có nguy cơ cháy nổ.
- **Bản đồ Phòng máy 2D (Interactive Floorplan):** Trực quan hóa vị trí tất cả Camera, Máy tính và Thiết bị IoT trên bản đồ phòng máy với thao tác kéo thả (Draggable) 2D.
- **Thu thập Dataset AI:** Hỗ trợ công cụ đóng gói dữ liệu mẫu AI (ảnh + metadata JSON keypoints) và xuất file ZIP trọn bộ phục vụ báo cáo bảo vệ ĐATN.
- **Giám sát Hiệu năng & Sao lưu Cấu hình:** Theo dõi chỉ số phần cứng CPU, RAM, Disk, Python Memory bằng `psutil` và hỗ trợ Xuất/Nhập (Export/Import) toàn bộ cấu hình hệ thống dạng JSON.

---

## II. KIẾN TRÚC & NHIỆM VỤ CHI TIẾT CỦA TỪNG THƯ MỤC

Hệ thống được tổ chức theo kiến trúc phân lớp chuẩn (**Clean Layered Architecture / MVC**):

```
DATN_GiamSatPhongMay_CNTT/
├── app/                        # Gói ứng dụng chính Flask Application Package
│   ├── __init__.py             # Application Factory Pattern (khởi tạo app & nạp cấu hình)
│   ├── models/                 # Tầng Dữ liệu (SQLAlchemy ORM Models)
│   │   ├── __init__.py         # Export tập trung các models
│   │   ├── audit_log.py        # Model bảng audit_logs (Lưu nhật ký thao tác hệ thống)
│   │   ├── camera.py           # Model bảng cameras (Quản lý Camera, RTSP URL, Tọa độ 2D)
│   │   ├── computer.py         # Model bảng computers (Quản lý Máy tính, IP, MAC, Tọa độ 2D)
│   │   ├── event.py            # Model bảng events (Lưu vết các sự kiện vi phạm an toàn)
│   │   ├── iot_device.py       # Model bảng iot_devices (Danh mục nút IoT ESP32)
│   │   ├── login_log.py        # Model bảng login_logs (Lưu lịch sử đăng nhập/đăng xuất)
│   │   ├── roi.py              # Model bảng rois (Tọa độ polygon vùng nguy cơ & ngưỡng giây)
│   │   ├── room.py             # Model bảng rooms (Danh mục Phòng máy)
│   │   ├── setting.py          # Model bảng system_settings (Cấu hình Telegram, IoT, Tham số)
│   │   └── user.py             # Model bảng users (Tài khoản, Mật khẩu pbkdf2, Phân quyền)
│   ├── services/               # Tầng Nghiệp vụ (Business Logic Layer)
│   │   ├── alert_engine.py     # Thuật toán Ray Casting kiểm tra ROI, đếm timer & Cooldown
│   │   ├── camera_service.py   # Quản lý luồng Camera (CameraManager Pool), đọc frame & Stream MJPEG
│   │   ├── esp32_service.py    # Giao tiếp HTTP REST tới ESP32, nhận Heartbeat & Cảnh báo Cháy/Khói
│   │   ├── pose_analyzer.py    # Phân tích khớp cơ thể MediaPipe Pose & phân loại tư thế (Đứng/Cúi/Ngồi/Quỳ)
│   │   ├── system_service.py   # Thu thập hiệu năng phần cứng thực tế (CPU, RAM, Disk, Process Memory)
│   │   └── telegram_service.py # Gọi Telegram Bot API gửi thông báo text và ảnh vi phạm
│   ├── routes/                 # Tầng Điều hướng Controller
│   │   ├── web/                # Quản lý Render Giao diện HTML Pages
│   │   │   ├── __init__.py
│   │   │   ├── auth_views.py   # View đăng nhập / đăng xuất (`/auth/login`, `/auth/logout`)
│   │   │   └── main_views.py   # Views trang chủ (`/dashboard`, `/monitor`, `/floorplan`, `/roi`, `/alerts`, `/dataset`, `/statistics`, `/reports`, `/settings`, `/accounts`, `/audit-logs`, `/iot`)
│   │   └── api/                # Quản lý RESTful APIs trả về dữ liệu JSON
│   │       ├── __init__.py
│   │       ├── camera_api.py   # CRUD API cho Camera (`/api/cameras`)
│   │       ├── computer_api.py # CRUD API cho Máy tính (`/api/computers`)
│   │       ├── dataset_api.py  # API Chụp mẫu, xem danh sách, xóa & Tải trọn bộ ZIP (`/api/dataset/*`)
│   │       ├── floorplan_api.py# API Trạng thái 2D & Lưu vị trí kéo thả (`/api/floorplan/*`)
│   │       ├── iot_api.py      # API Nhận Heartbeat & Điều khiển thiết bị (`/api/iot/*`)
│   │       ├── iot_device_api.py # CRUD API cho Danh mục IoT (`/api/iot_devices`)
│   │       ├── reports_api.py  # API Xuất báo cáo PDF tiếng Việt (`/api/reports/*`)
│   │       ├── roi_api.py      # CRUD API cho ROI & Lấy danh sách sự kiện (`/api/rois`, `/api/events`)
│   │       ├── room_api.py     # CRUD API cho Phòng máy (`/api/rooms`)
│   │       ├── settings_api.py # API Cấu hình, Test Telegram, System Metrics & Export/Import JSON (`/api/settings/*`)
│   │       └── statistics_api.py # API Thống kê số liệu Chart.js (`/api/statistics/data`)
│   ├── static/                 # Tài nguyên tĩnh Frontend
│   │   ├── css/                # Style Vanilla CSS & AdminLTE 3.2 custom
│   │   ├── js/                 # Thư viện JavaScript & Ajax Handlers
│   │   ├── images/             # Logo trường VIU, biểu tượng & Ảnh placeholder
│   │   ├── floorplan_config.json # File cấu hình sơ đồ bản đồ 2D
│   │   └── uploads/            # Thư mục lưu trữ ảnh chứng cứ vi phạm & tập mẫu Dataset
│   ├── templates/              # Giao diện HTML (Jinja2 Templates)
│   │   ├── auth/               # Template trang Đăng nhập (`login.html`)
│   │   ├── cameras/            # Template Quản lý Camera (`index.html`)
│   │   ├── computers/          # Template Quản lý Máy tính (`index.html`)
│   │   ├── iot_devices/        # Template Quản lý Thiết bị IoT (`index.html`)
│   │   ├── rooms/              # Template Quản lý Phòng máy (`index.html`)
│   │   ├── alerts.html         # Giao diện Quản lý Lịch sử Cảnh báo
│   │   ├── accounts.html       # Giao diện Quản lý Tài khoản Người dùng
│   │   ├── audit_logs.html     # Giao diện Nhật ký Thao tác Hệ thống
│   │   ├── base.html           # Layout khung chính AdminLTE 3.2 (Sidebar, Navbar, Footer)
│   │   ├── dashboard.html      # Trang Bảng điều khiển Tổng quan Realtime
│   │   ├── dataset.html        # Trang Quản lý & Đóng gói Dataset AI
│   │   ├── floorplan.html      # Trang Bản đồ Phòng máy 2D Tương tác
│   │   ├── iot.html            # Trang Điều khiển ESP32 & Bộ Giả lập Cảm biến Tương tác
│   │   ├── monitor.html        # Trang Giám sát Trực tiếp Multi-Camera & Siren Alarm
│   │   ├── reports.html        # Trang Xuất Báo cáo PDF
│   │   ├── roi.html            # Trang Cấu hình Vẽ vùng nguy cơ ROI Polygon
│   │   ├── settings.html       # Trang Cấu hình Hệ thống, Sao lưu & Hiệu năng
│   │   └── statistics.html     # Trang Thống kê & Biểu đồ Chart.js
│   └── utils/                  # Tiện ích bổ trợ
│       ├── audit.py            # Hàm ghi log nhật ký hệ thống `log_audit()`
│       └── decorators.py       # Custom Decorator `@admin_required` phân quyền
├── database/                   # Thư mục chứa cơ sở dữ liệu SQLite (`lab_monitor.db`)
├── firmware/                   # Mã nguồn C++ / Arduino cài đặt cho bo mạch ESP32
├── tests/                      # Thư mục chứa bộ kịch bản kiểm thử tích hợp tự động
│   └── test_system.py          # Kịch bản kiểm thử 15 bài test toàn diện hệ thống
├── requirements.txt            # Danh sách thư viện Python phụ thuộc
└── run.py                      # File khởi chạy server Flask chính
```

---

## III. CHI TIẾT TẤT CẢ CHỨC NĂNG HỆ THỐNG

### 1. Phân hệ Giám sát Trực tiếp & Nhận diện Tư thế AI (Live Monitor)
- **Xem video thời gian thực:** Nhúng trực tiếp luồng MJPEG `/video_feed/<camera_id>` trên web.
- **Hỗ trợ Đa Camera (Multi-Camera Grid):** Cho phép xem đồng thời nhiều luồng camera trong cùng phòng máy.
- **Tùy chỉnh Bố cục Lưới:** Bộ chuyển đổi linh hoạt chế độ xem `1x1 (Toàn màn hình)`, `2x2 (Lưới 4 camera)` và `3x3`.
- **Nhận diện Tư thế Realtime:** Tự động vẽ khung xương (Skeleton) đè lên video và gán nhãn 4 tư thế:
  - `Đứng` (Bình thường - Mức Low)
  - `Ngồi` (Mức High nếu trong gầm bàn)
  - `Cúi người` (Mức Medium)
  - `Quỳ` (Mức High - Nguy cơ cao gầm case máy tính)
- **Còi báo động Web (Web Audio Siren Alarm):** Phát âm thanh còi hú trực tiếp trên trình duyệt khi có sự cố nghiêm trọng. Có nút **🔊 Bật/Tắt âm báo** lưu trạng thái `localStorage`.

### 2. Phân hệ Quản lý Vùng Nguy cơ ROI (Polygon ROI Canvas)
- **Công cụ Vẽ Polygon Động:** Cho phép dùng chuột nhấp từng điểm để vẽ vùng nguy cơ với số đỉnh tùy ý đè lên ảnh snapshot camera.
- **Cấu hình Ngưỡng Thời gian:** Thiết lập số giây vi phạm tối đa (ví dụ: quá 5 giây cúi/quỳ trong ROI thì kích hoạt báo động).
- **Phân cấp Mức độ:** Gán nhãn mức độ nguy hiểm (`High`, `Medium`, `Low`) cho từng ROI.

### 3. Phân hệ Bản đồ 2D Phòng máy (Interactive Floorplan)
- **Trực quan hóa Vị trí 2D:** Hiển thị vị trí thực tế của tất cả Camera, Máy tính và Thiết bị IoT trên sơ đồ mặt bằng 2D.
- **Kéo thả chỉnh sửa (Draggable 2D):** Bật chế độ chỉnh sửa để kéo thả thay đổi vị trí thiết bị và tự động lưu tọa độ `x_pos`, `y_pos` vào SQLite DB via AJAX API.
- **Cảnh báo Đỏ Realtime:** Tự động nhấp nháy đỏ khu vực phòng máy trên bản đồ khi đang có sự cố vi phạm xảy ra.

### 4. Phân hệ Quản trị Danh mục Đa phòng (Multi-Room CRUD)
- **Mở rộng không giới hạn:** Quản lý linh hoạt nhiều Phòng máy, Camera, Máy tính và Nút IoT.
- **Modal CRUD đầy đủ:** Giao diện Modal Thêm mới, Chỉnh sửa thông tin, và Xóa thiết bị hoạt động trên 100% AJAX không reload trang.

### 5. Phân hệ Cảnh báo Tự động & Telegram Bot "Ban Ban"
- **Thuật toán Ray Casting (Point-in-Polygon):** Xác định chính xác keypoint hông/vai người có đang lọt vào bên trong polygon ROI hay không.
- **Tự động Gửi Telegram:** Chụp ảnh frame vi phạm, vẽ khung đỏ cảnh báo kèm thông tin thời gian, tên phòng, tên ROI và loại tư thế vi phạm gửi ngay tới Telegram Bot.
- **Cơ chế Cooldown:** Tự động khóa spam 60 giây cho mỗi ROI để tránh gửi trùng lặp tin nhắn khi sự kiện đang diễn ra.

### 6. Phân hệ IoT Gateway & Cảm biến Môi trường
- **Cơ chế Heartbeat:** Liên tục kiểm tra kết nối với ESP32 theo chu kỳ, tự động đánh dấu `Online` / `Offline`.
- **Đo đạc Cảm biến Môi trường:** Thu thập thông số Nhiệt độ (°C), Độ ẩm (%), Cảm biến Khói/Gas và Trạng thái Cửa phòng máy.
- **Tự động Báo động Cháy/Khói:** Khi Nhiệt độ > 45°C hoặc Cảm biến Khói kích hoạt (`smoke == 1`), hệ thống tự động:
  1. Gửi lệnh kích hoạt Còi hú & Đèn LED báo động tới bo mạch ESP32.
  2. Bắn tin nhắn cảnh báo khẩn cấp màu đỏ 🚨 qua Telegram Bot.
- **Bảng Giả lập Cảm biến Tương tác (IoT Simulator):** Bảng điều khiển giả lập trên trang `/iot` cho phép kéo slider Nhiệt độ và bấm nút Khói/Cửa để Demo trực tiếp trước Hội đồng bảo vệ mà không cần phần cứng thật.

### 7. Bộ Thu thập & Đóng gói Dataset AI (Dataset Collector Tool)
- **Nút Chụp Dataset (`📸 Chụp Dataset`):** Bấm trực tiếp trên trang Giám sát để lưu mẫu frame ảnh hiện tại kèm dữ liệu annotation (keypoint, độ tin cậy %, ROI polygon, pose label).
- **Trang Quản lý Gallery (`/dataset`):** Xem lại danh sách ảnh mẫu, lọc theo nhãn tư thế, xem dữ liệu JSON chi tiết và xóa mẫu hỏng.
- **Tải trọn gói ZIP (`Export Dataset`):** Nút nén và tải trọn bộ tập dữ liệu mẫu dưới dạng file `.zip` (`/api/dataset/download_zip`) làm minh chứng sản phẩm ĐATN.

### 8. Phân hệ Giám sát Hiệu năng Phần cứng (System Metrics)
- **Tích hợp `psutil`:** Đo đạc chỉ số thực của máy chủ: % CPU (Số nhân), % RAM (GB đã dùng / Tổng GB), % Dung lượng đĩa, Bộ nhớ RAM của riêng ứng dụng Python (MB), và Số luồng Thread đang chạy ngầm.
- **Thanh tiến trình Realtime:** Hiển thị đẹp mắt trên Dashboard và Cài đặt để khẳng định hệ thống hoạt động tối ưu, không rò rỉ bộ nhớ.

### 9. Phân hệ Sao lưu & Khôi phục Cấu hình (Config Backup & Restore)
- **Xuất cấu hình JSON (`Export JSON`):** Đóng gói toàn bộ thông tin Phòng máy, Camera, Máy tính, IoT, ROI Polygon, Tọa độ 2D và Cài đặt hệ thống ra 1 file JSON duy nhất.
- **Khôi phục cấu hình JSON (`Import JSON`):** Tải file JSON lên để tái lập cấu hình hệ thống trên máy chủ mới chỉ trong 1 giây.

### 10. Phân hệ Thống kê, Báo cáo & Phân quyền Hệ thống
- **Biểu đồ Chart.js:** Xuất đồ thị đường theo dõi xu hướng vi phạm theo 24 giờ trong ngày (Hourly Trend Line Chart), biểu đồ tròn phân bố mức độ (Severity Pie Chart) và biểu đồ cột so sánh giữa các ROI.
- **Xuất Báo cáo PDF:** Xuất file báo cáo thống kê PDF tiếng Việt chuẩn hóa với thư viện ReportLab.
- **Phân quyền & Khóa tài khoản:** Phân quyền `Admin` và `Monitor`. Tự động khóa tài khoản 5 phút nếu đăng nhập sai mật khẩu 5 lần liên tiếp.
- **Nhật ký Hệ thống (Audit Logs):** Ghi vết chi tiết mọi thao tác Thêm/Sửa/Xóa và Đăng nhập của người dùng.

---

## IV. QUY TRÌNH VẬN HÀNH & LUỒNG DỮ LIỆU

```
[Luồng 1: Xử lý Video & AI Pose]
Webcam / RTSP Stream ──► CameraService (threading) ──► PoseAnalyzer (MediaPipe)
                                                             │
                                                     (Keypoints & Pose)
                                                             ▼
                                                    AlertEngine (Ray Casting)
                                                             │
                                                  (Kiểm tra ROI & Timer)
                                                             │
                                               ┌─────────────┴─────────────┐
                                               ▼                           ▼
                                      [Bình thường]               [Vượt ngưỡng thời gian]
                                       Stream MJPEG                        │
                                                                           ├─► Lưu Event SQLite DB
                                                                           ├─► Bắn Telegram Bot (Ban Ban)
                                                                           └─► Bật Còi/Đèn ESP32 & Web Siren
```

---

## V. KẾT QUẢ KIỂM THỬ TỰ ĐỘNG (INTEGRATION TESTS)

Hệ thống đi kèm bộ test tự động trọn gói tại `tests/test_system.py`:
- **Tổng số bài test:** 15/15 **PASSED (100% OK)**
- **Thời gian chạy:** 9.8 giây
- **Danh sách 15 bài test kiểm tra:**
  1. `test_health_check`: Kiểm tra đường dẫn `/health` và kết nối DB.
  2. `test_auth_login_logout`: Kiểm tra Đăng nhập Admin & Đăng xuất.
  3. `test_authenticated_routes`: Kiểm tra nạp thành công 100% 15 trang Web HTML (HTTP 200).
  4. `test_room_crud`: Kiểm tra Thêm/Sửa/Xóa Phòng máy qua REST API.
  5. `test_camera_crud`: Kiểm tra Thêm/Sửa/Xóa Camera qua REST API.
  6. `test_computer_crud`: Kiểm tra Thêm/Sửa/Xóa Máy tính qua REST API.
  7. `test_iot_device_crud`: Kiểm tra Thêm/Sửa/Xóa Thiết bị IoT qua REST API.
  8. `test_floorplan_apis`: Kiểm tra API Bản đồ 2D & Lưu vị trí kéo thả.
  9. `test_roi_and_events_apis`: Kiểm tra API ROI Polygon, Event logs & Camera Snapshot.
  10. `test_iot_heartbeat`: Kiểm tra API Heartbeat ESP32 & Trạng thái kết nối.
  11. `test_system_metrics_api`: Kiểm tra API đo hiệu năng phần cứng `psutil`.
  12. `test_dataset_capture_api`: Kiểm tra API Chụp mẫu Dataset AI.
  13. `test_dataset_page_and_zip_apis`: Kiểm tra Trang Dataset & API nén file ZIP.
  14. `test_config_export_import_apis`: Kiểm tra API Xuất/Nhập file cấu hình JSON.
  15. `test_statistics_data_api`: Kiểm tra API dữ liệu Thống kê Chart.js.

---

## VI. HƯỚNG DẪN KHỞI CHẠY HỆ THỐNG

### 1. Khởi chạy Ứng dụng Server
Mở terminal tại thư mục gốc dự án và chạy:
```bash
venv\Scripts\python.exe run.py
```
Ứng dụng sẽ khởi chạy tại đường dẫn: **http://localhost:5000**  
- **Tài khoản Admin mặc định:** `admin` / `admin123`

### 2. Khởi chạy Bộ Kiểm thử Tự động
```bash
venv\Scripts\python.exe tests/test_system.py
```

---
*Báo cáo được tổng hợp tự động chuẩn hóa phục vụ Thuyết minh và Bảo vệ Đồ án Tốt nghiệp CNTT.*
