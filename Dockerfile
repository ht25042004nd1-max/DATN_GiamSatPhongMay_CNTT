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

# Expose cổng 5000 mà Flask lắng nghe
EXPOSE 5000

# Chạy script tạo admin trước, sau đó mới chạy server
CMD ["/bin/sh", "-c", "python create_admin.py && python run.py"]
