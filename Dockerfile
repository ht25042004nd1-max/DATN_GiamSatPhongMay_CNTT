# Sử dụng base image Python 3.11-slim-bookworm (Debian mới nhất, ổn định hơn)
FROM python:3.11-slim-bookworm

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Đặt các biến môi trường
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Không cần cài các thư viện đồ họa hệ thống (như libgl1-mesa-glx)
# do chúng ta đã chuyển sang sử dụng opencv-python-headless trong requirements.txt

# Sao chép file requirements.txt trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các thư viện Python
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Tải model MediaPipe về trước để chứa sẵn trong image (tránh tải lại khi chạy container)
RUN python download_model.py

# Bỏ EXPOSE 5000 vì Render sẽ tự động gán biến môi trường PORT và quản lý port mạng

# Chạy script tạo admin lần đầu, sau đó chạy server Flask bằng Gunicorn với đa luồng (--threads 10) để hỗ trợ Streaming Video
CMD ["/bin/sh", "-c", "python create_admin.py && gunicorn --threads 10 --bind 0.0.0.0:$PORT run:app"]
