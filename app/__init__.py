# ============================================================
# app/__init__.py — Khởi tạo ứng dụng Flask (Application Factory)
# Pattern "Application Factory" giúp dễ test và mở rộng sau này
# ============================================================
import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv

# Khởi tạo các extension dùng chung (chưa gắn vào flask_app)
db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    """
    Hàm factory tạo và cấu hình ứng dụng Flask.
    Trả về instance flask_app đã sẵn sàng chạy.
    """
    load_dotenv()

    # Flask Package: templates & static nằm trong app package (app/templates, app/static)
    flask_app = Flask(__name__,
                      template_folder='templates',
                      static_folder='static')

    # --- Cấu hình cơ bản ---
    flask_app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-fallback')

    # Lấy đường dẫn CSDL từ biến môi trường (Render, Cloud...)
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        # Aiven thêm ?ssl-mode=REQUIRED vào cuối, nhưng PyMySQL không hiểu tham số này. Ta cần cắt nó đi.
        if '?ssl-mode=' in db_url:
            db_url = db_url.split('?')[0]

        # Đảm bảo SQLAlchemy sử dụng PyMySQL để kết nối
        if db_url.startswith('mysql://'):
            db_url = db_url.replace('mysql://', 'mysql+pymysql://', 1)
        
        flask_app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        
        # Bắt buộc bật SSL (Aiven yêu cầu) nhưng bỏ qua việc tải file chứng chỉ rườm rà
        if 'mysql+pymysql' in db_url:
            flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'ssl': {}}}
    else:
        # Fallback về SQLite khi chạy trên máy cá nhân
        db_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'database', 'lab_monitor.db')
        )
        flask_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Tắt để tránh cảnh báo

    # --- Gắn extension vào flask_app ---
    db.init_app(flask_app)
    login_manager.init_app(flask_app)

    # Trang login mặc định khi chưa đăng nhập
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Vui lòng đăng nhập để tiếp tục.'
    login_manager.login_message_category = 'warning'

    # --- Đăng ký các Blueprint (Web Views & RESTful APIs) ---
    from app.routes.web.main_views import main_bp
    from app.routes.web.auth_views import auth_bp
    from app.routes.api.roi_api import roi_bp
    from app.routes.api.settings_api import settings_bp
    from app.routes.api.iot_api import iot_bp
    from app.routes.api.statistics_api import stats_bp
    from app.routes.api.reports_api import reports_bp
    from app.routes.api.floorplan_api import floorplan_bp
    from app.routes.api.room_api import room_bp
    from app.routes.api.camera_api import camera_bp
    from app.routes.api.computer_api import computer_bp
    from app.routes.api.iot_device_api import iot_device_bp
    from app.routes.api.dataset_api import dataset_bp

    flask_app.register_blueprint(main_bp)
    flask_app.register_blueprint(auth_bp, url_prefix='/auth')
    flask_app.register_blueprint(roi_bp)
    flask_app.register_blueprint(settings_bp)
    flask_app.register_blueprint(iot_bp)
    flask_app.register_blueprint(stats_bp)
    flask_app.register_blueprint(reports_bp)
    flask_app.register_blueprint(floorplan_bp)
    flask_app.register_blueprint(room_bp)
    flask_app.register_blueprint(camera_bp)
    flask_app.register_blueprint(computer_bp)
    flask_app.register_blueprint(iot_device_bp)
    flask_app.register_blueprint(dataset_bp)

    # --- Cấu hình Flask-Login: hàm load user theo ID từ session ---
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- Xử lý lỗi HTTP ---
    @flask_app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @flask_app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    # --- Tạo bảng database nếu chưa tồn tại ---
    with flask_app.app_context():
        # Import models để SQLAlchemy nhận diện và tạo bảng
        import app.models

        # Đảm bảo thư mục database tồn tại
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db.create_all()

    # --- Khởi động Telegram Long Polling ---
    try:
        from app.services.telegram_service import start_polling
        start_polling()
    except Exception as e:
        print(f"Không thể khởi động Telegram polling: {e}")

    # --- Khởi động Auto-Ping Service ---
    try:
        from app.services.ping_service import ping_service
        ping_service.init_app(flask_app)
        ping_service.start()
    except Exception as e:
        print(f"Không thể khởi động PingService: {e}")

    return flask_app
