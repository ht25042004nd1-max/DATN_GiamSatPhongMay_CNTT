import json
from flask import request
from flask_login import current_user
from app import db
from app.models.audit_log import AuditLog

def log_audit(action, target_type=None, target_id=None, details=None):
    """
    Ghi lại lịch sử hoạt động vào bảng AuditLog.
    
    :param action: Chuỗi hành động (ví dụ: 'LOGIN_SUCCESS', 'UPDATE_ROI')
    :param target_type: Loại đối tượng bị tác động (ví dụ: 'ROI', 'User')
    :param target_id: ID của đối tượng bị tác động
    :param details: Thông tin chi tiết (string hoặc dict). Nếu là dict sẽ được serialize sang JSON.
    """
    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        ip_address = request.remote_addr if request else None

        if isinstance(details, dict):
            details_str = json.dumps(details, ensure_ascii=False)
        else:
            details_str = str(details) if details else None

        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details_str,
            ip_address=ip_address
        )
        
        db.session.add(audit_log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Trong thực tế có thể log ra file hoặc console để debug
        print(f"Error logging audit: {e}")
