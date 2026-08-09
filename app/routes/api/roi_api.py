# ============================================================
# app/routes/roi_routes.py — CRUD API cho ROI và Events
# ============================================================
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from app import db
from app.models.roi import ROI
from app.models.event import Event
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

roi_bp = Blueprint('roi_api', __name__, url_prefix='/api')


# ══════════════════════════════════════════════════════════
# ROI CRUD
# ══════════════════════════════════════════════════════════

@roi_bp.route('/rois', methods=['GET'])
@login_required
def get_rois():
    """Lấy danh sách tất cả ROI."""
    camera_id = request.args.get('camera_id')
    query = ROI.query
    if camera_id:
        query = query.filter_by(camera_id=camera_id)
    rois = query.order_by(ROI.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rois])


@roi_bp.route('/rois', methods=['POST'])
@login_required
@admin_required
def create_roi():
    """Tạo ROI mới."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Thiếu dữ liệu'}), 400

    points = data.get('points', [])
    if len(points) < 3:
        return jsonify({'error': 'Polygon cần ít nhất 3 điểm'}), 400

    roi = ROI(
        name               = data.get('name', 'ROI mới'),
        level              = data.get('level', 'medium'),
        is_active          = data.get('is_active', True),
        duration_threshold = int(data.get('duration_threshold', 5)),
        camera_id          = data.get('camera_id')
    )
    roi.points = points  # dùng setter để serialize JSON

    db.session.add(roi)
    db.session.commit()
    log_audit('CREATE_ROI', 'ROI', roi.id, {'name': roi.name, 'level': roi.level})

    # Buộc AlertEngine refresh cache
    try:
        from app.services.alert_engine import alert_engine
        alert_engine.invalidate_cache()
    except Exception:
        pass

    return jsonify(roi.to_dict()), 201


@roi_bp.route('/rois/<int:roi_id>', methods=['PUT'])
@login_required
@admin_required
def update_roi(roi_id):
    """Sửa ROI (tên, level, threshold, bật/tắt, points)."""
    roi  = ROI.query.get_or_404(roi_id)
    data = request.get_json()

    if 'name' in data:
        roi.name = data['name']
    if 'level' in data:
        roi.level = data['level']
    if 'is_active' in data:
        roi.is_active = bool(data['is_active'])
    if 'duration_threshold' in data:
        val = int(data['duration_threshold'])
        roi.duration_threshold = max(3, min(30, val))  # clamp 3–30
    if 'camera_id' in data:
        roi.camera_id = data['camera_id']
    if 'points' in data:
        if len(data['points']) < 3:
            return jsonify({'error': 'Polygon cần ít nhất 3 điểm'}), 400
        roi.points = data['points']

    db.session.commit()
    log_audit('UPDATE_ROI', 'ROI', roi.id, {'name': roi.name, 'is_active': roi.is_active})

    try:
        from app.services.alert_engine import alert_engine
        alert_engine.invalidate_cache()
    except Exception:
        pass

    return jsonify(roi.to_dict())


@roi_bp.route('/rois/<int:roi_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_roi(roi_id):
    """Xóa ROI."""
    roi = ROI.query.get_or_404(roi_id)
    roi_name = roi.name
    db.session.delete(roi)
    db.session.commit()
    log_audit('DELETE_ROI', 'ROI', roi_id, {'name': roi_name})

    try:
        from app.services.alert_engine import alert_engine
        alert_engine.invalidate_cache()
    except Exception:
        pass

    return jsonify({'message': f'Đã xóa ROI #{roi_id}'})


@roi_bp.route('/rois/<int:roi_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_roi(roi_id):
    """Bật/tắt nhanh ROI."""
    roi = ROI.query.get_or_404(roi_id)
    roi.is_active = not roi.is_active
    db.session.commit()
    log_audit('TOGGLE_ROI', 'ROI', roi.id, {'name': roi.name, 'is_active': roi.is_active})

    try:
        from app.services.alert_engine import alert_engine
        alert_engine.invalidate_cache()
    except Exception:
        pass

    return jsonify({'is_active': roi.is_active, 'roi': roi.to_dict()})


# ══════════════════════════════════════════════════════════
# EVENTS (cảnh báo)
# ══════════════════════════════════════════════════════════

@roi_bp.route('/events', methods=['GET'])
@login_required
def get_events():
    """
    Lấy danh sách events với bộ lọc.
    Query params: status, level, limit (mặc định 100)
    """
    status = request.args.get('status')
    level  = request.args.get('level')
    limit  = min(int(request.args.get('limit', 100)), 500)

    q = Event.query.order_by(Event.started_at.desc())
    if status:
        q = q.filter_by(status=status)
    if level:
        q = q.filter_by(level=level)

    events = q.limit(limit).all()
    return jsonify([e.to_dict() for e in events])


@roi_bp.route('/events/count', methods=['GET'])
@login_required
def get_events_count():
    """Đếm số event chưa duyệt (pending) để cập nhật badge sidebar."""
    pending_count = Event.query.filter_by(status='pending').count()
    total          = Event.query.count()
    return jsonify({'new': pending_count, 'total': total})


@roi_bp.route('/events/<int:event_id>', methods=['PATCH'])
@login_required
def update_event_status(event_id):
    """Cập nhật trạng thái event: pending -> confirmed / ignored."""
    from datetime import datetime
    ev   = Event.query.get_or_404(event_id)
    data = request.get_json()

    allowed_statuses = {'pending', 'confirmed', 'ignored'}
    new_status = data.get('status')
    if new_status not in allowed_statuses:
        return jsonify({'error': f'Status không hợp lệ. Chọn: {allowed_statuses}'}), 400

    ev.status = new_status
    if new_status in {'confirmed', 'ignored'}:
        ev.handled_by = current_user.id
        ev.handled_at = datetime.utcnow()

    if 'note' in data:
        ev.note = data['note']
    db.session.commit()
    log_audit('UPDATE_EVENT_STATUS', 'Event', ev.id, {'status': new_status})
    return jsonify(ev.to_dict())


@roi_bp.route('/events/mark_all_seen', methods=['POST'])
@login_required
def mark_all_seen():
    """Đánh dấu tất cả event 'pending' thành 'ignored'."""
    from datetime import datetime
    Event.query.filter_by(status='pending').update({
        'status': 'ignored',
        'handled_by': current_user.id,
        'handled_at': datetime.utcnow()
    })
    db.session.commit()
    log_audit('MARK_ALL_EVENTS_SEEN', 'Event', None, {})
    return jsonify({'message': 'Đã đánh dấu tất cả là đã bỏ qua'})


@roi_bp.route('/events/<int:event_id>/send_telegram', methods=['POST'])
@login_required
def send_event_telegram(event_id):
    """
    Gửi cảnh báo Telegram thủ công cho một event cụ thể.
    Body JSON (tuỳ chọn): { "force": true }
      - force=true: bỏ qua kiểm tra telegram_enabled và khung giờ hoạt động.
    """
    import os
    from app.services.telegram_service import send_message, send_photo, _get_config, _in_active_hours, _clean_token, LEVEL_EMOJI, POSE_VN
    from datetime import datetime

    ev = Event.query.get_or_404(event_id)
    data = request.get_json(silent=True) or {}
    force = bool(data.get('force', False))

    cfg = _get_config()

    if not cfg['token'] or not cfg['chat_id']:
        return jsonify({'success': False, 'message': 'Chưa cấu hình Token hoặc Chat ID Telegram. Vào Cài đặt để nhập.'}), 400

    if not force:
        if not cfg['enabled']:
            return jsonify({
                'success': False,
                'message': 'Telegram đang bị tắt trong cài đặt. Dùng "Gửi bắt buộc" để bỏ qua.'
            }), 400
        if not _in_active_hours(cfg['hour_from'], cfg['hour_to']):
            return jsonify({
                'success': False,
                'message': f'Ngoài khung giờ hoạt động ({cfg["hour_from"]}h–{cfg["hour_to"]}h). Dùng "Gửi bắt buộc" để bỏ qua.'
            }), 400

    # ─── Xây dựng nội dung tin nhắn đầy đủ ───────────────────
    emoji     = LEVEL_EMOJI.get(ev.level, '⚠️')
    pose_vn   = POSE_VN.get(ev.pose, ev.pose or 'N/A')
    dur_secs  = ev.duration_seconds
    dur_str   = f"{dur_secs // 60}p{dur_secs % 60}s" if dur_secs >= 60 else f"{dur_secs}s"
    started   = ev.started_at.strftime('%d/%m/%Y %H:%M:%S') if ev.started_at else 'N/A'
    ended     = ev.ended_at.strftime('%d/%m/%Y %H:%M:%S') if ev.ended_at else 'Chưa kết thúc'
    status_vn = {'pending': 'Chờ xử lý', 'confirmed': 'Đã xác nhận', 'ignored': 'Đã bỏ qua'}.get(ev.status, ev.status)
    level_vn  = {'low': 'Thấp', 'medium': 'Trung bình', 'high': 'Cao'}.get(ev.level, ev.level)
    confidence_str = f"{ev.confidence_score * 100:.1f}%" if ev.confidence_score is not None else 'N/A'
    sent_by   = current_user.display_name or current_user.username
    manual_tag = '🔔 <b>[GỬI THỦ CÔNG]</b>' if force else '🔔 <b>[GỬI TỪ HỆ THỐNG]</b>'

    caption = (
        f"{manual_tag}\n"
        f"{emoji} <b>CẢNH BÁO — {level_vn.upper()}</b>\n\n"
        f"📍 <b>Khu vực (ROI):</b> {ev.roi_name or 'N/A'}\n"
        f"🤸 <b>Tư thế vi phạm:</b> {pose_vn}\n"
        f"📊 <b>Mức độ:</b> {level_vn}\n"
        f"🎯 <b>Độ tin cậy AI:</b> {confidence_str}\n"
        f"👥 <b>Số người phát hiện:</b> {ev.person_count}\n"
        f"⏱ <b>Thời lượng vi phạm:</b> {dur_str}\n"
        f"🕐 <b>Bắt đầu:</b> {started}\n"
        f"🕑 <b>Kết thúc:</b> {ended}\n"
        f"📋 <b>Trạng thái:</b> {status_vn}\n"
        f"🔖 <b>Mã sự kiện:</b> #{ev.id}\n"
        f"👤 <b>Gửi bởi:</b> {sent_by}"
    )

    # ─── Thử gửi ảnh minh chứng nếu có ──────────────────────
    img_path = os.path.join('static', 'uploads', 'events', f'{ev.id}.jpg')
    frame_bytes = None
    if os.path.exists(img_path):
        try:
            with open(img_path, 'rb') as f:
                frame_bytes = f.read()
        except Exception:
            frame_bytes = None

    token   = cfg['token']
    chat_id = cfg['chat_id']

    try:
        if frame_bytes:
            ok = send_photo(token, chat_id, frame_bytes, caption)
        else:
            ok = send_message(token, chat_id, caption)

        if ok:
            return jsonify({'success': True, 'message': f'Đã gửi cảnh báo #{ev.id} tới Telegram thành công!', 'has_image': bool(frame_bytes)})
        else:
            return jsonify({'success': False, 'message': 'Gửi Telegram thất bại — kiểm tra Token và Chat ID trong Cài đặt.'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi kết nối Telegram: {str(e)}'}), 500


# ══════════════════════════════════════════════════════════
# Snapshot camera (dùng cho canvas vẽ ROI)
# ══════════════════════════════════════════════════════════

@roi_bp.route('/camera_snapshot')
@login_required
def camera_snapshot():
    """
    Trả về 1 frame JPEG tĩnh để làm nền canvas vẽ ROI.
    Query param: camera_id (int, bắt buộc)
    """
    import io
    from flask import send_file
    try:
        from app.routes.web.main_views import _get_camera
        camera_id = request.args.get('camera_id', type=int)
        if camera_id is None:
            # Lấy camera đầu tiên nếu không có tham số
            from app.models.camera import Camera
            cam_model = Camera.query.filter_by(is_active=True).first()
            camera_id = cam_model.id if cam_model else 1

        cam = _get_camera(camera_id)
        frame_bytes = cam.get_frame()
        resp = send_file(io.BytesIO(frame_bytes), mimetype='image/jpeg')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        return resp
    except Exception as e:
        return jsonify({'error': str(e)}), 500

