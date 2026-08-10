# ============================================================
# app/routes/web/main_views.py — Web View Controllers (HTML Templates)
# ============================================================
import os
from flask import (Blueprint, render_template, Response,
                   redirect, url_for, jsonify, request, flash)
from flask_login import login_required, current_user
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

main_bp = Blueprint('main', __name__)

def _get_camera(camera_id):
    """Trả về camera tương ứng từ CameraManager."""
    from app.services.camera_service import camera_manager
    from app.models.camera import Camera
    
    cam_model = Camera.query.get(camera_id)
    source = 0
    if cam_model and cam_model.rtsp_url:
        if cam_model.rtsp_url.isdigit():
            source = int(cam_model.rtsp_url)
        else:
            source = cam_model.rtsp_url

    fallback = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'static', 'sample', 'sample.mp4'
    ))
    return camera_manager.get_camera(camera_id, source=source, fallback_video=fallback)

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@main_bp.route('/health')
def health_check():
    try:
        from app import db
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok', 'db': 'ok'}), 200
    except Exception as e:
        return jsonify({'status': 'degraded', 'error': str(e)}), 503

@main_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', active_page='dashboard')

@main_bp.route('/monitor')
@login_required
def monitor():
    from app.models.room import Room
    rooms = Room.query.all()
    return render_template('monitor.html', rooms=rooms, active_page='monitor')

@main_bp.route('/video_feed/<int:camera_id>')
@login_required
def video_feed(camera_id):
    from app.models.camera import Camera
    cam_model = Camera.query.get(camera_id)
    if not cam_model:
        # Camera không tồn tại, trả về ảnh tĩnh
        placeholder = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'static', 'images', 'placeholder.png'
        ))
        if os.path.exists(placeholder):
            with open(placeholder, 'rb') as f:
                data = f.read()
            from flask import make_response
            resp = make_response(data)
            resp.headers['Content-Type'] = 'image/png'
            return resp
        return Response('Camera not found', 404)
    cam = _get_camera(camera_id)
    def generate():
        import time
        while True:
            frame_bytes = cam.get_frame()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n'
                   + frame_bytes +
                   b'\r\n')
            time.sleep(0.05)
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@main_bp.route('/camera_status/<int:camera_id>')
@login_required
def camera_status(camera_id):
    from app.models.camera import Camera
    cam_model = Camera.query.get(camera_id)
    if not cam_model:
        return jsonify({
            'error': 'Camera không tồn tại',
            'is_online': False,
            'fps': 0.0,
            'pose_enabled': False,
            'pose': {'is_detected': False, 'pose': 'Không có camera', 'confidence': 0},
            'source_name': 'N/A',
            'timestamp': ''
        }), 404
    cam = _get_camera(camera_id)
    return jsonify(cam.get_status())

@main_bp.route('/roi')
@login_required
@admin_required
def roi():
    return render_template('roi.html', active_page='roi')

@main_bp.route('/alerts')
@login_required
def alerts():
    return render_template('alerts.html', active_page='alerts')

@main_bp.route('/dataset')
@login_required
@admin_required
def dataset_page():
    return render_template('dataset.html', active_page='dataset')

@main_bp.route('/statistics')
@login_required
def statistics():
    return render_template('statistics.html', active_page='statistics')

@main_bp.route('/reports')
@login_required
def reports():
    return render_template('reports.html', active_page='reports')

@main_bp.route('/settings')
@login_required
@admin_required
def settings():
    return render_template('settings.html', active_page='settings')

@main_bp.route('/accounts')
@login_required
@admin_required
def accounts():
    from app.models.user import User
    # Ẩn tất cả tài khoản có quyền admin khỏi danh sách
    users = User.query.filter(User.role != 'admin').order_by(User.id.desc()).all()
    return render_template('accounts.html', users=users, active_page='accounts')

@main_bp.route('/accounts/create', methods=['POST'])
@login_required
@admin_required
def create_account():
    from app import db
    from app.models.user import User

    security_code = request.form.get('security_code', '')
    if security_code != os.getenv('ADMIN_SECURITY_CODE', '199999'):
        flash('Mã xác thực Admin không chính xác!', 'danger')
        return redirect(url_for('main.accounts'))

    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    display_name = request.form.get('display_name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    role = request.form.get('role', 'monitor')

    if role == 'admin':
        flash('Không được phép tạo thêm tài khoản với quyền admin.', 'danger')
        return redirect(url_for('main.accounts'))

    if not username or not password:
        flash('Tên đăng nhập và mật khẩu không được để trống.', 'danger')
        return redirect(url_for('main.accounts'))

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash(f'Tên đăng nhập "{username}" đã tồn tại.', 'danger')
        return redirect(url_for('main.accounts'))

    if email:
        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash(f'Email "{email}" đã được sử dụng.', 'danger')
            return redirect(url_for('main.accounts'))

    user = User(
        username=username,
        display_name=display_name or None,
        email=email or None,
        phone=phone or None,
        role=role
    )
    user.set_password(password)

    try:
        db.session.add(user)
        db.session.commit()
        log_audit('CREATE_USER', 'User', user.id, {'username': username, 'role': role})
        flash(f'Tạo tài khoản "{username}" thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi tạo tài khoản: {str(e)}', 'danger')

    return redirect(url_for('main.accounts'))

@main_bp.route('/accounts/edit/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def edit_account(user_id):
    from app import db
    from app.models.user import User

    security_code = request.form.get('security_code', '')
    if security_code != os.getenv('ADMIN_SECURITY_CODE', '199999'):
        flash('Mã xác thực Admin không chính xác!', 'danger')
        return redirect(url_for('main.accounts'))

    user = User.query.get_or_404(user_id)
    role = request.form.get('role', user.role)
    if user.id == current_user.id and role != 'admin' and user.role == 'admin':
        flash('Bạn không thể tự hạ quyền giám sát (role) của chính mình.', 'warning')
        role = 'admin'
    elif role == 'admin' and user.role != 'admin':
        flash('Không được phép cấp quyền admin cho tài khoản khác.', 'danger')
        return redirect(url_for('main.accounts'))

    display_name = request.form.get('display_name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()

    if email and email != user.email:
        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash(f'Email "{email}" đã được sử dụng bởi tài khoản khác.', 'danger')
            return redirect(url_for('main.accounts'))

    user.display_name = display_name or None
    user.email = email or None
    user.phone = phone or None
    user.role = role

    try:
        db.session.commit()
        log_audit('EDIT_USER', 'User', user.id, {'username': user.username, 'new_role': role})
        flash(f'Cập nhật tài khoản "{user.username}" thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi cập nhật: {str(e)}', 'danger')

    return redirect(url_for('main.accounts'))

@main_bp.route('/accounts/reset_password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    from app import db
    from app.models.user import User

    security_code = request.form.get('security_code', '')
    if security_code != os.getenv('ADMIN_SECURITY_CODE', '199999'):
        flash('Mã xác thực Admin không chính xác!', 'danger')
        return redirect(url_for('main.accounts'))

    user = User.query.get_or_404(user_id)
    password = request.form.get('password', '')

    if not password:
        flash('Mật khẩu mới không được để trống.', 'danger')
        return redirect(url_for('main.accounts'))

    user.set_password(password)

    try:
        db.session.commit()
        log_audit('RESET_PASSWORD', 'User', user.id, {'username': user.username})
        flash(f'Đã đặt lại mật khẩu cho tài khoản "{user.username}" thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi đặt lại mật khẩu: {str(e)}', 'danger')

    return redirect(url_for('main.accounts'))

@main_bp.route('/accounts/unlock/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def unlock_account(user_id):
    from app import db
    from app.models.user import User

    security_code = request.form.get('security_code', '')
    if security_code != os.getenv('ADMIN_SECURITY_CODE', '199999'):
        flash('Mã xác thực Admin không chính xác!', 'danger')
        return redirect(url_for('main.accounts'))

    user = User.query.get_or_404(user_id)
    user.failed_attempts = 0
    user.locked_until = None

    try:
        db.session.commit()
        log_audit('UNLOCK_USER', 'User', user.id, {'username': user.username})
        flash(f'Đã mở khóa thành công cho tài khoản "{user.username}"!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi mở khóa: {str(e)}', 'danger')

    return redirect(url_for('main.accounts'))

@main_bp.route('/accounts/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_account(user_id):
    from app import db
    from app.models.user import User

    security_code = request.form.get('security_code', '')
    if security_code != os.getenv('ADMIN_SECURITY_CODE', '199999'):
        flash('Mã xác thực Admin không chính xác!', 'danger')
        return redirect(url_for('main.accounts'))

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Bạn không thể tự xóa tài khoản của chính mình khi đang đăng nhập.', 'danger')
        return redirect(url_for('main.accounts'))

    if user.username == 'admin':
        flash('Không được phép xóa tài khoản admin mặc định hệ thống.', 'danger')
        return redirect(url_for('main.accounts'))

    try:
        username = user.username
        db.session.delete(user)
        db.session.commit()
        log_audit('DELETE_USER', 'User', user_id, {'username': username})
        flash(f'Đã xóa tài khoản "{username}" khỏi hệ thống.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi xóa tài khoản: {str(e)}', 'danger')

    return redirect(url_for('main.accounts'))

@main_bp.route('/audit-logs')
@login_required
@admin_required
def audit_logs():
    from app.models.audit_log import AuditLog
    logs = AuditLog.query.order_by(AuditLog.id.desc()).limit(200).all()
    return render_template('audit_logs.html', logs=logs, active_page='audit_logs')

@main_bp.route('/iot')
@login_required
@admin_required
def iot():
    return render_template('iot.html', active_page='iot')

@main_bp.route('/streamer/<int:camera_id>')
@login_required
def streamer(camera_id):
    return render_template('streamer.html', camera_id=camera_id, active_page='cameras')
