# ============================================================
# app/routes/api/dataset_api.py — Công cụ Chụp & Đóng gói Dataset AI
# ============================================================
import os
import json
import time
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, send_file
from flask_login import login_required
from app.utils.decorators import admin_required

dataset_bp = Blueprint('dataset', __name__, url_prefix='/api/dataset')

DATASET_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'uploads', 'dataset')
)

@dataset_bp.route('/capture', methods=['POST'])
@login_required
def capture_dataset_frame():
    """
    Chụp 1 frame hiện tại từ Camera kèm theo annotation metadata (keypoints, ROI, pose)
    để phục vụ xây dựng bộ Dataset ĐATN.
    """
    from app.services.camera_service import camera_manager
    from app.models.roi import ROI

    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id', 1)
    label = data.get('label', '')
    note = data.get('note', '')

    cam = camera_manager.get_camera(camera_id)
    if not cam:
        return jsonify({'error': 'Camera không khả dụng'}), 404

    frame_bytes = cam.get_frame()
    cam_status = cam.get_status()
    pose_info = cam_status.get('pose', {})

    os.makedirs(DATASET_DIR, exist_ok=True)

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    img_filename = f"sample_{timestamp_str}.jpg"
    meta_filename = f"sample_{timestamp_str}.json"

    img_path = os.path.join(DATASET_DIR, img_filename)
    meta_path = os.path.join(DATASET_DIR, meta_filename)

    try:
        with open(img_path, 'wb') as f:
            f.write(frame_bytes)
    except Exception as e:
        return jsonify({'error': f'Không thể ghi file ảnh: {str(e)}'}), 500

    rois = ROI.query.filter_by(camera_id=camera_id).all() if camera_id else []

    metadata = {
        'timestamp': datetime.now().isoformat(),
        'camera_id': camera_id,
        'user_label': label or pose_info.get('pose', 'Unlabeled'),
        'ai_detected_pose': pose_info.get('pose', 'N/A'),
        'confidence': pose_info.get('confidence', 0.0),
        'is_detected': pose_info.get('is_detected', False),
        'note': note,
        'image_filename': img_filename,
        'rois': [{'id': r.id, 'name': r.name, 'level': r.level, 'points': r.points} for r in rois]
    }

    try:
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({'error': f'Không thể ghi file metadata: {str(e)}'}), 500

    return jsonify({
        'success': True,
        'message': f'Đã lưu mẫu Dataset thành công!',
        'image_url': f'/static/uploads/dataset/{img_filename}',
        'meta_url': f'/static/uploads/dataset/{meta_filename}'
    }), 201

@dataset_bp.route('/samples', methods=['GET'])
@login_required
def list_dataset_samples():
    """Lấy danh sách các mẫu Dataset đã chụp."""
    if not os.path.exists(DATASET_DIR):
        return jsonify([])

    samples = []
    for fname in os.listdir(DATASET_DIR):
        if fname.endswith('.json'):
            try:
                with open(os.path.join(DATASET_DIR, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['id'] = fname.replace('.json', '')
                    samples.append(data)
            except Exception:
                pass
    samples.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify(samples)

@dataset_bp.route('/samples/<sample_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_sample(sample_id):
    """Xóa mẫu dataset (.jpg và .json)."""
    img_file = os.path.join(DATASET_DIR, f"{sample_id}.jpg")
    json_file = os.path.join(DATASET_DIR, f"{sample_id}.json")

    deleted = False
    if os.path.exists(img_file):
        os.remove(img_file)
        deleted = True
    if os.path.exists(json_file):
        os.remove(json_file)
        deleted = True

    if deleted:
        return jsonify({'message': f'Đã xóa mẫu {sample_id}'})
    return jsonify({'error': 'Không tìm thấy mẫu dataset'}), 404

@dataset_bp.route('/download_zip', methods=['GET'])
@login_required
def download_dataset_zip():
    """Nén toàn bộ thư mục Dataset thành file .zip để người dùng tải về."""
    import zipfile
    import io

    if not os.path.exists(DATASET_DIR) or not os.listdir(DATASET_DIR):
        return jsonify({'error': 'Chưa có dữ liệu Dataset để nén'}), 404

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for fname in os.listdir(DATASET_DIR):
            fpath = os.path.join(DATASET_DIR, fname)
            if os.path.isfile(fpath):
                zip_file.write(fpath, arcname=fname)

    zip_buffer.seek(0)
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'VIU_Lab_Dataset_{timestamp_str}.zip'
    )
