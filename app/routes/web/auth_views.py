# ============================================================
# app/routes/web/auth_views.py — Auth Web Controllers (Login/Logout)
# ============================================================
from datetime import datetime, timedelta
from flask import (Blueprint, render_template, redirect,
                   url_for, request, flash)
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from app.models.user import User
from app.models.login_log import LoginLog
from app.utils.audit import log_audit

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 5

auth_bp = Blueprint('auth', __name__)

def _ghi_log_dang_nhap(user_id, username_input, status, note=None):
    log = LoginLog(
        user_id        = user_id,
        username_input = username_input,
        ip_address     = request.remote_addr,
        user_agent     = request.headers.get('User-Agent', '')[:300],
        status         = status,
        note           = note
    )
    db.session.add(log)
    db.session.commit()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if user is None:
            _ghi_log_dang_nhap(None, username, 'failed', 'Tên đăng nhập không tồn tại')
            log_audit('LOGIN_FAILED', 'User', None, {'username_input': username, 'reason': 'Username not found'})
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
            return render_template('auth/login.html')

        if user.is_locked():
            con_lai = (user.locked_until - datetime.utcnow()).seconds // 60 + 1
            _ghi_log_dang_nhap(user.id, username, 'failed', 'Đăng nhập khi tài khoản đang bị khóa')
            log_audit('LOGIN_FAILED', 'User', user.id, {'username_input': username, 'reason': 'Account locked'})
            flash(f'Tài khoản bị khóa tạm {LOCKOUT_MINUTES} phút do nhập sai quá nhiều lần. '
                  f'Vui lòng thử lại sau {con_lai} phút.', 'warning')
            return render_template('auth/login.html')

        if not user.check_password(password):
            user.failed_attempts += 1

            if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                db.session.commit()
                _ghi_log_dang_nhap(user.id, username, 'failed',
                                   f'Sai mật khẩu lần {user.failed_attempts} → Khóa tài khoản')
                log_audit('LOGIN_FAILED', 'User', user.id, {'username_input': username, 'reason': 'Wrong password (locked)'})
                flash(f'Sai mật khẩu {MAX_FAILED_ATTEMPTS} lần liên tiếp. '
                      f'Tài khoản bị khóa {LOCKOUT_MINUTES} phút.', 'danger')
            else:
                db.session.commit()
                con_lai_lan = MAX_FAILED_ATTEMPTS - user.failed_attempts
                _ghi_log_dang_nhap(user.id, username, 'failed',
                                   f'Sai mật khẩu lần {user.failed_attempts}')
                log_audit('LOGIN_FAILED', 'User', user.id, {'username_input': username, 'reason': 'Wrong password'})
                flash(f'Mật khẩu không đúng. Còn {con_lai_lan} lần thử trước khi tài khoản bị khóa.', 'danger')

            return render_template('auth/login.html')

        # Đăng nhập thành công
        user.failed_attempts = 0
        user.locked_until = None
        user.last_login = datetime.utcnow()
        db.session.commit()

        login_user(user)

        _ghi_log_dang_nhap(user.id, username, 'success', 'Đăng nhập thành công')
        log_audit('LOGIN_SUCCESS', 'User', user.id, {'username': username, 'role': user.role})

        flash(f'Xin chào, {user.display_name or user.username}! Đăng nhập thành công.', 'success')

        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)

        return redirect(url_for('main.dashboard'))

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    username = current_user.username
    user_id  = current_user.id
    logout_user()
    log_audit('LOGOUT', 'User', user_id, {'username': username})
    flash('Đã đăng xuất khỏi hệ thống.', 'info')
    return redirect(url_for('auth.login'))
