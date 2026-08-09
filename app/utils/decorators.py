# ============================================================
# app/utils/decorators.py — Decorator bảo vệ route
# ============================================================
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


def admin_required(f):
    """
    Decorator yêu cầu người dùng phải có vai trò 'admin'.
    Dùng bên trên @login_required ở các route chỉ admin mới được vào.

    Cách dùng:
        @app.route('/admin/something')
        @login_required
        @admin_required
        def admin_page():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Kiểm tra user đã đăng nhập và có quyền admin không
        if not current_user.is_authenticated or current_user.role != 'admin':
            # Trả về HTTP 403 Forbidden thay vì redirect để rõ ràng hơn
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def monitor_required(f):
    """
    Decorator yêu cầu người dùng phải là 'monitor' hoặc 'admin'.
    (Tức là bất kỳ tài khoản hợp lệ nào đã đăng nhập đều được)
    Dùng kết hợp với @login_required.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role not in ('admin', 'monitor'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
