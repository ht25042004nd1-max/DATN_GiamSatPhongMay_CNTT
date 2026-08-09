# LỘ TRÌNH ĐỒ ÁN TỐT NGHIỆP
## Ứng dụng thị giác máy tính và IoT trong giám sát phòng thực hành máy tính

**Thời gian thực hiện:** 10/08/2026 – 15/11/2026 (14 tuần)
**Nguyên tắc ưu tiên:** Bỏ qua giai đoạn lý thuyết thuần túy ở tuần đầu. Làm nhanh 3 việc "xương sống" trước — **Giao diện (dashboard)**, **Telegram bot "banban"**, **Demo webcam** — để có sản phẩm chạy được sớm, sau đó mới đắp dần các module xử lý ảnh, tư thế và IoT lên nền đó.

---

## GIAI ĐOẠN 1 — MVP NHANH: Giao diện + Bot banban + Webcam (Tuần 1–2)

Mục tiêu giai đoạn: sau 2 tuần có một hệ thống "rỗng nhưng chạy được": mở web thấy hình webcam, bấm nút là Telegram bot banban gửi được tin nhắn/ảnh, có khung giao diện để sau này gắn dần AI vào.

### Tuần 1 (10/08 – 16/08): Dựng khung 3 thành phần song song

| Việc | Chi tiết | Kết quả cần đạt | Trạng thái |
|---|---|---|---|
| Môi trường dev | Cài Python 3.10+, OpenCV (`opencv-python`), Flask hoặc FastAPI, git, tạo repo code | Chạy được `import cv2` không lỗi | ✅ Hoàn thành |
| Demo webcam | Viết script mở webcam bằng OpenCV, đọc từng frame, hiển thị bằng `cv2.imshow` để test phần cứng trước | Webcam bật lên, thấy hình local | ✅ Hoàn thành |
| Webcam → Web | Dựng server Flask/FastAPI nhỏ, stream webcam ra trình duyệt dạng MJPEG (route `/video_feed`) | Mở `http://localhost:5000/video_feed` thấy hình trực tiếp | ✅ Hoàn thành |
| Bot Telegram "banban" | Vào BotFather trên Telegram → `/newbot` → đặt tên hiển thị "banban" (username phải kết thúc bằng "bot", ví dụ `banban_alert_bot`) → lấy Token | Có Token bot, đã chat thử `/start` với bot | ✅ Hoàn thành |
| Test gửi tin nhắn | Viết script Python dùng `requests` hoặc thư viện `python-telegram-bot` gọi API `sendMessage` | Bot banban gửi được 1 tin nhắn text vào chat của bạn | ✅ Hoàn thành |
| Test gửi ảnh | Chụp 1 frame từ webcam, gọi API `sendPhoto` gửi qua Telegram | Bot banban gửi được ảnh chụp từ webcam | ✅ Hoàn thành |
| Khung giao diện | Dựng 1 trang HTML/CSS đơn giản (chưa cần đẹp): khung hiển thị video, khu vực "Danh sách sự kiện" (đang để trống/mock), nút "Test cảnh báo" | Có 1 trang web duy nhất chứa cả video + placeholder | ✅ Hoàn thành |

> Lưu ý: Chưa cần AI, chưa cần model gì cả — tuần này thuần là "nối dây" cho 3 khối chạy được độc lập.

### Tuần 2 (17/08 – 23/08): Ghép 3 khối lại thành một dashboard tối giản

| Việc | Chi tiết | Kết quả cần đạt | Trạng thái |
|---|---|---|---|
| Ghép giao diện + webcam | Nhúng luồng `/video_feed` vào đúng vị trí trên trang dashboard | Mở dashboard là thấy video trực tiếp, không cần mở tab riêng | ✅ Hoàn thành |
| Nút test → Telegram | Nút "Test cảnh báo" trên giao diện gọi API backend, backend chụp frame hiện tại + gọi bot banban gửi Telegram | Bấm nút trên web → điện thoại nhận được ảnh + tin nhắn từ banban | ✅ Hoàn thành |
| Cấu trúc log tối giản | Tạo bảng/file lưu sự kiện: thời gian, ảnh, loại cảnh báo (tạm thời là "test") | Có file `events.json` hoặc bảng DB nhỏ (SQLite) ghi lại mỗi lần test | ✅ Hoàn thành |
| Hiển thị danh sách sự kiện | Đọc log ở trên, render ra danh sách trên giao diện (mới nhất lên đầu) | Mỗi lần bấm test, danh sách trên web có thêm 1 dòng | ✅ Hoàn thành |
| Cấu hình cơ bản trên UI | Thêm ô nhập để bật/tắt gửi Telegram, chọn camera (nếu nhiều webcam) | Đổi cấu hình trên UI có tác dụng thật, không hardcode | ✅ Hoàn thành |

**Chốt giai đoạn 1:** Có 1 dashboard web chạy webcam trực tiếp, có nút test bắn cảnh báo Telegram qua bot banban, có log sự kiện hiển thị trên giao diện. Đây chính là "khung xương" — từ tuần 3 trở đi chỉ là nhét AI và IoT vào các chỗ trống này, không phải làm lại từ đầu.

---

## GIAI ĐOẠN 2 — Xử lý ảnh: Phát hiện người & tư thế (Tuần 3–6)

### Tuần 3 (24/08 – 30/08): Phát hiện người trong khung hình
- [x] Tìm hiểu nhanh YOLOv8 (bản pose hoặc detect) và MediaPipe Pose, chọn 1 hướng để làm chính (gợi ý: MediaPipe Pose nhẹ, dễ chạy CPU; YOLO-Pose chính xác hơn nhưng cần GPU để mượt).
- [x] Tích hợp model vào pipeline đang đọc frame từ webcam (chỗ đang stream ở Giai đoạn 1).
- [x] Vẽ khung/khung xương người phát hiện được đè lên video hiển thị trên dashboard.
- **Kết quả:** dashboard hiện video có khung bao quanh người xuất hiện trong khung hình. (✅ **Hoàn thành** - Đã tích hợp MediaPipe Pose để vẽ khung xương thời gian thực).

### Tuần 4 (31/08 – 06/09): Xác định vùng nguy cơ (ROI)
- [x] Thiết kế công cụ đơn giản để vẽ/khai báo tọa độ vùng nguy cơ (gầm bàn, cạnh/sau case) trên khung hình — có thể làm bằng cách click chuột lưu tọa độ, hoặc nhập tay trong file cấu hình.
- [x] Viết logic kiểm tra: điểm khớp cơ thể (keypoint) có nằm trong vùng ROI hay không.
- [x] Hiển thị vùng ROI vẽ đè lên video trên dashboard, đồng bộ với phần cấu hình đã làm ở Tuần 2.
- **Kết quả:** khai báo được vùng nguy cơ trên giao diện, hệ thống biết người có đang ở trong vùng đó không. (✅ **Hoàn thành** - Đã xây dựng Canvas vẽ Polygon ROI động và lưu cơ sở dữ liệu thành công).

### Tuần 5 (07/09 – 13/09): Nhận diện tư thế cúi/ngồi/quỳ
- [x] Dựa vào keypoint (vai, hông, đầu gối) tính góc/tỷ lệ để phân loại đứng / cúi / ngồi / quỳ.
- [x] Test với nhiều tư thế thật để tinh chỉnh ngưỡng góc.
- **Kết quả:** hệ thống gắn nhãn tư thế theo thời gian thực lên video. (✅ **Hoàn thành** - Nhận diện đầy đủ 4 tư thế và hiển thị trên màn hình monitor).

### Tuần 6 (14/09 – 20/09): Ngưỡng thời gian & logic bất thường
- [x] Kết hợp: người ở trong vùng nguy cơ + tư thế cúi/ngồi/quỳ + duy trì quá X giây → gắn cờ "bất thường".
- [x] Thêm ô cấu hình ngưỡng thời gian (X giây) ngay trên dashboard đã có từ Tuần 2.
- **Kết quả:** hệ thống tự phát hiện và đánh dấu sự kiện nghi vấn, chưa cần gửi cảnh báo thật (chỉ log nội bộ để kiểm tra độ chính xác). (✅ **Hoàn thành** - AlertEngine quét định kỳ và tạo sự kiện vi phạm tự động khi quá ngưỡng).

---

## GIAI ĐOẠN 3 — Module cảnh báo & tích hợp IoT (Tuần 7–9)

### Tuần 7 (21/09 – 27/09): Nối logic bất thường vào module cảnh báo có sẵn
- [x] Khi hệ thống gắn cờ "bất thường" (từ Tuần 6) → tự động chụp frame, ghi log, gọi bot banban gửi Telegram (tái sử dụng đúng hàm đã viết ở Tuần 1–2, giờ gọi tự động thay vì bấm nút).
- [x] Thêm chống spam: không gửi lặp lại liên tục cho cùng 1 sự kiện đang diễn ra.
- **Kết quả:** hệ thống tự phát hiện – tự cảnh báo Telegram, không cần người bấm nút nữa. (✅ **Hoàn thành** - Telegram tự động bắn ảnh vi phạm kèm khoanh vùng đỏ và thông tin vi phạm).

### Tuần 8 (28/09 – 04/10): Lập trình ESP32 nhận tín hiệu cảnh báo
- [x] Viết code Arduino/MicroPython cho ESP32: nhận tín hiệu qua HTTP (server gọi 1 API) hoặc MQTT (nếu dùng broker như Mosquitto).
- [x] ESP32 điều khiển đèn/còi khi nhận tín hiệu cảnh báo.
- **Kết quả:** server phát hiện bất thường → ESP32 bật đèn/còi thật. (✅ **Lập trình xong** - Đã xây dựng cơ chế gửi HTTP POST tới ESP32, mô phỏng phản hồi IoT và kiểm soát thiết bị LED/Buzzer/Relay).

### Tuần 9 (05/10 – 11/10): Tích hợp TCL-508L / HY-LandTiger V2.0 (nếu đề tài yêu cầu dùng cả 2 board)
- [ ] Áp dụng lại cùng cơ chế giao tiếp đã làm với ESP32 cho các board còn lại.
- [ ] Chuẩn hóa giao thức chung (HTTP/MQTT) để dashboard có thể gửi tín hiệu tới nhiều thiết bị.
- **Kết quả:** toàn bộ thiết bị IoT phản ứng đồng bộ khi có cảnh báo. (⏳ **Cần phát triển** - Cần triển khai tích hợp trực tiếp phần cứng thực tế và kiểm tra độ ổn định tín hiệu đa thiết bị).

---

## GIAI ĐOẠN 4 — Hoàn thiện dashboard & thử nghiệm thực tế (Tuần 10–11)

### Tuần 10 (12/10 – 18/10): Giao diện quản lý AdminLTE đồng bộ và Thống kê
- [x] Bổ sung các phần còn thiếu so với yêu cầu đề tài: xem lại ảnh minh chứng theo từng sự kiện, lọc theo thời gian, thống kê số lượng cảnh báo.
- [x] Làm giao diện gọn gàng, đồng bộ chuẩn AdminLTE 3.2.
- **Kết quả:** dashboard đáp ứng đủ mục "Xây dựng giao diện quản lý" trong đề cương. (✅ **Hoàn thành** - Đã chuyển đổi toàn bộ 100% trang Dashboard, Monitor, ROI, Cài đặt, Cảnh báo, Thống kê, Báo cáo sang AdminLTE 3.2).

### Tuần 11 (19/10 – 25/10): Thử nghiệm tại phòng thực hành thật (hoặc mô hình mẫu)
- [ ] Lắp đặt thử camera + ESP32 tại phòng thực hành thực tế của Khoa (hoặc dựng mô hình bàn/case mẫu nếu chưa xin được phòng thật).
- [ ] Thu thập dữ liệu thực tế → bắt đầu xây dựng bộ Dataset chính thức (ảnh có gắn nhãn tình huống bình thường/bất thường).
- **Kết quả:** có dữ liệu thật để tinh chỉnh ngưỡng và đánh giá ở giai đoạn sau. (⏳ **Cần phát triển** - Tiến hành lắp đặt thử nghiệm thực tế tại phòng lab của trường và xây dựng bộ Dataset).

---

## GIAI ĐOẠN 5 — Đánh giá hệ thống (Tuần 12–13)

### Tuần 12 (26/10 – 01/11): Đánh giá độ chính xác & độ trễ
- [ ] Đo tỷ lệ phát hiện đúng/sai (false positive, false negative) trên dataset thu được.
- [ ] Đo thời gian từ lúc xảy ra hành vi đến lúc Telegram/IoT nhận được cảnh báo.
- [ ] Tinh chỉnh lại ngưỡng thời gian, vùng ROI dựa trên kết quả đo. (⏳ **Cần phát triển** - Tinh chỉnh ngưỡng góc và ngưỡng giây của thuật toán pose khớp với thực tế phòng Lab).

### Tuần 13 (02/11 – 08/11): Đánh giá độ ổn định & hoàn thiện sản phẩm
- [ ] Chạy hệ thống liên tục nhiều giờ để kiểm tra rò rỉ bộ nhớ, crash, mất kết nối camera/IoT.
- [ ] Sửa lỗi phát sinh, đóng gói code, viết tài liệu hướng dẫn cài đặt/chạy hệ thống.
- [ ] Hoàn thiện toàn bộ 6 sản phẩm bàn giao: Dataset, code xử lý video, code ESP32/TCL-508L/HY-LandTiger, dashboard, demo hoàn chỉnh. (⏳ **Cần phát triển** - Đóng gói, kiểm định rò rỉ bộ nhớ của luồng stream camera chạy nền).

---

## GIAI ĐOẠN 6 — Báo cáo & bảo vệ (Tuần 14)

### Tuần 14 (09/11 – 15/11): Viết báo cáo, làm slide, tổng duyệt
- [ ] Viết Báo cáo ĐATN theo đúng mẫu Khoa (cơ sở lý thuyết viết lại lúc này, dựa trên những gì đã thực sự làm — nhanh hơn viết trước khi có sản phẩm).
- [ ] Làm slide trình bày theo mẫu, chuẩn bị kịch bản demo trực tiếp (webcam → phát hiện → Telegram banban → đèn/còi ESP32 sáng).
- [ ] Chạy thử toàn bộ demo ít nhất 2–3 lần trước ngày báo cáo để tránh lỗi bất ngờ. (⏳ **Cần phát triển** - Hoàn tất báo cáo giấy và tổng duyệt demo trước hội đồng bảo vệ).
