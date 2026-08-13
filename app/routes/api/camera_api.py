# ============================================================
# app/routes/api/camera_api.py — RESTful API cho Camera
# ============================================================
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app import db
from app.models.camera import Camera
from app.models.room import Room
from app.utils.decorators import admin_required
from app.utils.audit import log_audit

camera_bp = Blueprint('camera', __name__)

@camera_bp.route('/cameras')
@login_required
def index():
    cameras = Camera.query.order_by(Camera.id.desc()).all()
    rooms = Room.query.all()
    return render_template('cameras/index.html', cameras=cameras, rooms=rooms, active_page='cameras')

@camera_bp.route('/api/cameras', methods=['GET'])
@login_required
def get_cameras():
    room_id = request.args.get('room_id')
    query = Camera.query
    if room_id:
        query = query.filter_by(room_id=room_id)
    cameras = query.order_by(Camera.is_active.desc(), Camera.id.asc()).all()
    return jsonify([c.to_dict() for c in cameras])

@camera_bp.route('/api/cameras', methods=['POST'])
@login_required
@admin_required
def create_camera():
    data = request.get_json()
    if not data or not data.get('name') or not data.get('room_id'):
        return jsonify({'error': 'Thiếu tên hoặc phòng máy'}), 400

    camera = Camera(
        name=data['name'],
        rtsp_url=data.get('rtsp_url'),
        room_id=data['room_id'],
        is_active=data.get('is_active', True)
    )
    db.session.add(camera)
    db.session.commit()
    log_audit('CREATE_CAMERA', 'Camera', camera.id, {'name': camera.name})
    return jsonify(camera.to_dict()), 201

@camera_bp.route('/api/cameras/<int:camera_id>', methods=['PUT'])
@login_required
@admin_required
def update_camera(camera_id):
    camera = Camera.query.get_or_404(camera_id)
    data = request.get_json()
    
    if 'name' in data: camera.name = data['name']
    if 'rtsp_url' in data: camera.rtsp_url = data['rtsp_url']
    if 'room_id' in data: camera.room_id = data['room_id']
    if 'is_active' in data: camera.is_active = bool(data['is_active'])
        
    db.session.commit()
    
    from app.services.camera_service import camera_manager
    camera_manager.remove_camera(camera_id)

    log_audit('UPDATE_CAMERA', 'Camera', camera.id, {'name': camera.name})
    return jsonify(camera.to_dict())

@camera_bp.route('/api/cameras/<int:camera_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_camera(camera_id):
    camera = Camera.query.get_or_404(camera_id)
    name = camera.name
    
    from app.services.camera_service import camera_manager
    camera_manager.remove_camera(camera_id)

    db.session.delete(camera)
    db.session.commit()
    log_audit('DELETE_CAMERA', 'Camera', camera_id, {'name': name})
    return jsonify({'message': 'Đã xóa camera thành công'})

@camera_bp.route('/api/cameras/<int:camera_id>/test_connection', methods=['GET', 'POST'])
@login_required
def test_connection(camera_id):
    """Kiểm tra kết nối tới Camera (Webcam, RTSP, IP Phone Cam, Client Cam)."""
    import cv2
    from app.services.camera_service import camera_manager, ClientCamera
    camera = Camera.query.get_or_404(camera_id)
    rtsp = (camera.rtsp_url or '').strip()
    
    if not rtsp:
        return jsonify({'status': 'error', 'message': 'Chưa cấu hình URL hoặc Nguồn Camera!'}), 400
        
    if rtsp.lower() == 'client_camera':
        cam_service = camera_manager.get_camera(camera_id, source='client_camera')
        if isinstance(cam_service, ClientCamera):
            has_frame = cam_service.frame is not None
            fps = cam_service.fps
            return jsonify({
                'status': 'ok' if has_frame else 'waiting',
                'type': 'client_camera',
                'message': f'Đang nhận luồng từ trạm phát ({fps} FPS)' if has_frame else 'Chờ thiết bị (điện thoại/laptop) mở trang Trạm Phát (/streamer) để truyền frame.',
                'fps': fps,
                'is_online': cam_service.is_online
            })
    
    # Thử mở bằng cv2 VideoCapture
    src = int(rtsp) if rtsp.isdigit() else rtsp
    import platform
    is_win = platform.system() == 'Windows'
    if isinstance(src, int) and is_win:
        cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(src)

    if cap.isOpened():
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            h, w = frame.shape[:2]
            return jsonify({
                'status': 'ok',
                'type': 'stream',
                'resolution': f'{w}x{h}',
                'message': f'Kết nối thành công tới nguồn {rtsp} (Độ phân giải: {w}x{h})'
            })
        else:
            return jsonify({'status': 'error', 'message': f'Nguồn {rtsp} mở được nhưng không đọc được dữ liệu hình ảnh.'})
    else:
        return jsonify({'status': 'error', 'message': f'Không thể kết nối tới {rtsp}. Vui lòng kiểm tra lại IP/URL hoặc kết nối WiFi.'})

@camera_bp.route('/api/cameras/<int:camera_id>/upload_frame', methods=['POST'])
def upload_frame(camera_id):
    """API nhận frame dạng Base64 từ Client Camera và cập nhật vào CameraManager."""
    import base64
    import cv2
    import numpy as np
    from app.services.camera_service import camera_manager, ClientCamera

    data = request.get_json()
    if not data or 'image' not in data:
        return jsonify({'error': 'No image data'}), 400

    # Lấy base64 string, bỏ phần header (vd: data:image/jpeg;base64,...)
    image_data = data['image']
    if ',' in image_data:
        image_data = image_data.split(',')[1]

    try:
        # Decode base64 thành mảng bytes
        img_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        # Decode bytes thành ảnh BGR cho OpenCV
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is not None:
            # Lấy camera từ manager (nếu nó là client_camera thì sẽ update được)
            cam_service = camera_manager.get_camera(camera_id, source="client_camera")
            if isinstance(cam_service, ClientCamera):
                cam_service.update_frame(frame)
                return jsonify({'status': 'ok'}), 200
            else:
                return jsonify({'error': 'Camera này không phải là ClientCamera'}), 400
        else:
            return jsonify({'error': 'Invalid image format'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
