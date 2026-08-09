# ============================================================
# create_admin.py — Script tạo tài khoản Admin lần đầu
#
# Cách chạy (chỉ cần chạy 1 lần duy nhất):
#   python create_admin.py
# ============================================================
import sys
import os

# Đảm bảo Python tìm được package 'app' (chạy từ thư mục gốc dự án)
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app import create_app, db
from app.models.user import User

# Thông tin tài khoản Admin mặc định
# (Sau khi tạo xong, hãy đổi mật khẩu qua giao diện quản trị)
DEFAULT_USERNAME     = 'admin'
DEFAULT_PASSWORD     = 'admin123'
DEFAULT_DISPLAY_NAME = 'Quản Trị Viên'


def create_admin():
    app = create_app()

    with app.app_context():
        # Kiểm tra tài khoản admin đã tồn tại chưa để tránh tạo trùng
        existing = User.query.filter_by(username=DEFAULT_USERNAME).first()
        if existing:
            print(f"[!] Tài khoản '{DEFAULT_USERNAME}' đã tồn tại. Không tạo thêm.")
            print(f"    Vai trò hiện tại: {existing.role}")
            return

        # Tạo user mới với vai trò 'admin'
        admin = User(
            username     = DEFAULT_USERNAME,
            role         = 'admin',
            display_name = DEFAULT_DISPLAY_NAME,
        )

        # Băm mật khẩu trước khi lưu vào database
        admin.set_password(DEFAULT_PASSWORD)

        db.session.add(admin)
        db.session.commit()

        print("=" * 50)
        print("[OK] Tao tai khoan Admin thanh cong!")
        print(f"     Ten dang nhap : {DEFAULT_USERNAME}")
        print(f"     Mat khau      : {DEFAULT_PASSWORD}")
        print(f"     Vai tro       : admin")
        print("=" * 50)
        print("[!] Hay doi mat khau sau khi dang nhap lan dau!")


if __name__ == '__main__':
    create_admin()
