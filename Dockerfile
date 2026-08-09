# Sử dụng base image Python 3.11-slim (Debian)
FROM python:3.11-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Đặt các biến môi trường
# PYTHONUNBUFFERED=1 giúp log print hiển thị ngay lập tức trong console
# PYTHONDONTWRITEBYTECODE=1 ngăn Python ghi các file .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Cài đặt các thư viện hệ thống cần thiết cho OpenCV và MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Sao chép file requirements.txt trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các thư viện Python
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Tải model MediaPipe về trước để chứa sẵn trong image (tránh tải lại khi chạy container)
RUN python download_model.py

# Expose cổng 5000 mà Flask lắng nghe
EXPOSE 5000

# Chạy ứng dụng Flask
CMD ["python", "run.py"]
