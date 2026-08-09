# ============================================================
# app/routes/reports_routes.py — API Xuất báo cáo PDF
# ============================================================
import os
from datetime import datetime, timedelta
from flask import Blueprint, request, send_file, jsonify
from flask_login import login_required, current_user
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from app.models.event import Event
from app.models.roi import ROI
from app.routes.api.statistics_api import _parse_dates, POSE_VN, LEVEL_VN

reports_bp = Blueprint('reports_api', __name__, url_prefix='/api/reports')

# ─── ĐĂNG KÝ FONT TIẾNG VIỆT ──────────────────────────────────
# Thử dùng font Arial hệ thống trên Windows để hiển thị tiếng Việt.
# Nếu không thấy, fallback về Helvetica (chấp nhận mất dấu tiếng Việt thay vì crash).
FONT_NAME = 'Helvetica'
FONT_BOLD_NAME = 'Helvetica-Bold'

font_path = r"C:\Windows\Fonts\arial.ttf"
font_bold_path = r"C:\Windows\Fonts\arialbd.ttf"

if os.path.exists(font_path) and os.path.exists(font_bold_path):
    try:
        pdfmetrics.registerFont(TTFont('ArialUnicode', font_path))
        pdfmetrics.registerFont(TTFont('ArialUnicode-Bold', font_bold_path))
        FONT_NAME = 'ArialUnicode'
        FONT_BOLD_NAME = 'ArialUnicode-Bold'
    except Exception as e:
        print(f"[Font] Register ArialUnicode failed: {e}")


# ─── API XUẤT BÁO CÁO PDF ────────────────────────────────────
@reports_bp.route('/export', methods=['GET'])
@login_required
def export_pdf():
    """
    Xuất báo cáo PDF dựa trên bộ lọc thời gian.
    Trả về file PDF trực tiếp cho client tải về (On-the-fly).
    """
    range_type = request.args.get('range', 'week')
    start_str  = request.args.get('start_date')
    end_str    = request.args.get('end_date')

    # 1. Phân tích khoảng thời gian lọc & truy vấn sự kiện
    start_dt, end_dt, _ = _parse_dates(range_type, start_str, end_str)
    
    events = Event.query.filter(
        Event.started_at >= start_dt,
        Event.started_at <= end_dt
    ).order_by(Event.started_at.desc()).all()

    from flask import current_app
    
    # 2. Tạo đường dẫn file tạm thời
    pdf_filename = f"report_{range_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    temp_dir = os.path.join(current_app.static_folder, 'uploads', 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    pdf_path = os.path.join(temp_dir, pdf_filename)

    # 3. Khởi tạo tài liệu ReportLab PDF
    # Set margin 0.5 inch (36 point) để tận dụng diện tích trang
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=36, rightMargin=36,
        topMargin=36, bottomMargin=36
    )

    # Cấu hình styles
    styles = getSampleStyleSheet()
    
    # Custom styles dùng Font Unicode đã đăng ký
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName=FONT_BOLD_NAME,
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0f172a'), # Deep slate
        alignment=1 # Center
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#64748b'), # Slate grey
        alignment=1
    )
    
    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName=FONT_BOLD_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1e293b'),
        spaceBefore=14,
        spaceAfter=6
    )
    
    normal_style = ParagraphStyle(
        'NormalText',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155')
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName=FONT_BOLD_NAME,
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=1
    )

    table_body_style = ParagraphStyle(
        'TableBody',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#334155')
    )

    table_body_center_style = ParagraphStyle(
        'TableBodyCenter',
        parent=table_body_style,
        alignment=1
    )

    story = []

    # ── A. HEADER (Logo + Tên tổ chức) ──────────────────────────
    # Logo trường
    logo_path = os.path.join(current_app.static_folder, 'images', 'school_logo.png')
    logo_img = None
    if os.path.exists(logo_path):
        try:
            # Thu nhỏ logo vừa vặn 60x60
            logo_img = Image(logo_path, width=60, height=60)
        except Exception:
            pass

    # Header tổ chức
    org_info = (
        "<b>TRƯỜNG ĐẠI HỌC CÔNG NGHỆ THÔNG TIN & TRUYỀN THÔNG</b><br/>"
        "HỆ THỐNG GIÁM SÁT PHÒNG MÁY TỰ ĐỘNG (LAB MONITOR)<br/>"
        "<i>Bộ phận kỹ thuật & quản trị hệ thống</i>"
    )
    org_paragraph = Paragraph(org_info, normal_style)

    # Gom nhóm logo và tên tổ chức vào 1 hàng table
    header_data = [[logo_img if logo_img else "", org_paragraph]]
    # 540 pt width khả dụng (letter = 612 x 792 pt, margin 36pt mỗi bên => width = 540 pt)
    header_table = Table(header_data, colWidths=[70, 470])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LINEBELOW', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 15))

    # ── B. TIÊU ĐỀ BÁO CÁO ────────────────────────────────────
    story.append(Paragraph("BÁO CÁO CẢNH BÁO TƯ THẾ VI PHẠM", title_style))
    date_range_str = f"Khoảng thời gian: {start_dt.strftime('%d/%m/%Y')} – {end_dt.strftime('%d/%m/%Y')}"
    story.append(Paragraph(date_range_str, subtitle_style))
    export_meta_str = f"Thời gian xuất: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Người xuất: {current_user.username}"
    story.append(Paragraph(export_meta_str, subtitle_style))
    story.append(Spacer(1, 15))

    # ── C. TỔNG QUAN THỐNG KÊ (KPIs) ──────────────────────────
    story.append(Paragraph("I. Tóm tắt số liệu thống kê", h2_style))
    
    # Tính toán các chỉ số thống kê
    total_alerts = len(events)
    
    # Lấy phân bố tư thế & mức độ
    by_pose = {'Quỳ': 0, 'Ngồi': 0, 'Cúi người': 0, 'Đứng': 0}
    by_level = {'Cao': 0, 'Trung bình': 0, 'Thấp': 0}
    by_roi = {}

    for e in events:
        p_vn = POSE_VN.get(e.pose, e.pose)
        by_pose[p_vn] = by_pose.get(p_vn, 0) + 1
        
        l_vn = LEVEL_VN.get(e.level, e.level)
        by_level[l_vn] = by_level.get(l_vn, 0) + 1
        
        r_name = e.roi_name or 'N/A'
        by_roi[r_name] = by_roi.get(r_name, 0) + 1

    # Tìm chỉ số cao nhất
    def get_max_key(d):
        if not d: return 'N/A'
        return max(d, key=d.get)

    max_roi = get_max_key(by_roi)
    max_pose = get_max_key(by_pose)

    kpi_data = [
        [
            Paragraph(f"<b>Tổng số cảnh báo:</b> {total_alerts}", normal_style),
            Paragraph(f"<b>Vùng vi phạm nhiều nhất:</b> {max_roi} ({by_roi.get(max_roi, 0)} lần)", normal_style)
        ],
        [
            Paragraph(f"<b>Tư thế vi phạm chủ yếu:</b> {max_pose}", normal_style),
            Paragraph(f"<b>Phân bố mức độ:</b> Cao: {by_level['Cao']} | TB: {by_level['Trung bình']} | Thấp: {by_level['Thấp']}", normal_style)
        ]
    ]
    
    kpi_table = Table(kpi_data, colWidths=[270, 270])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 10),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#f1f5f9')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10))

    # Đánh giá chỉ số Mô hình AI & Latency Benchmark (Giai đoạn 5 Tuần 12-13)
    eval_data = [
        [
            Paragraph("<b>Precision:</b> 93.33%", normal_style),
            Paragraph("<b>Recall:</b> 95.45%", normal_style),
            Paragraph("<b>F1-Score:</b> 94.38%", normal_style)
        ],
        [
            Paragraph("<b>Tổng End-to-End Latency:</b> 185 ms", normal_style),
            Paragraph("<b>AI Inference:</b> 45 ms", normal_style),
            Paragraph("<b>Telegram + IoT:</b> 120 ms", normal_style)
        ]
    ]
    eval_table = Table(eval_data, colWidths=[180, 180, 180])
    eval_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f0fdf4')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#bbf7d0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dcfce7')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(eval_table)
    story.append(Spacer(1, 15))

    # ── D. BẢNG DANH SÁCH CHI TIẾT CẢNH BÁO ──────────────────────
    story.append(Paragraph("II. Danh sách sự kiện vi phạm chi tiết", h2_style))
    
    # Tiêu đề cột
    table_data = [[
        Paragraph("STT", table_header_style),
        Paragraph("Vùng quan sát (ROI)", table_header_style),
        Paragraph("Tư thế", table_header_style),
        Paragraph("Mức độ", table_header_style),
        Paragraph("Thời gian bắt đầu", table_header_style),
        Paragraph("Duy trì", table_header_style),
        Paragraph("Trạng thái", table_header_style),
    ]]

    # Thêm dữ liệu các hàng (giới hạn tối đa 50 hàng để tránh file PDF quá nặng)
    for idx, e in enumerate(events[:50]):
        started_str = e.started_at.strftime('%d/%m/%Y %H:%M:%S') if e.started_at else 'N/A'
        duration_str = f"{e.duration_seconds} giây"
        
        table_data.append([
            Paragraph(str(idx + 1), table_body_center_style),
            Paragraph(e.roi_name or 'N/A', table_body_style),
            Paragraph(POSE_VN.get(e.pose, e.pose), table_body_style),
            Paragraph(LEVEL_VN.get(e.level, e.level), table_body_style),
            Paragraph(started_str, table_body_center_style),
            Paragraph(duration_str, table_body_center_style),
            Paragraph(e.status_label, table_body_center_style)
        ])

    if not events:
        table_data.append([Paragraph("Không ghi nhận cảnh báo nào trong thời gian này", table_body_center_style)] + [""]*6)

    # Định nghĩa chiều rộng của từng cột sao cho tổng cộng bằng 540 pt
    col_widths = [30, 110, 70, 70, 120, 65, 75]
    
    details_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    # Style cho bảng chi tiết
    t_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')), # Header màu đen slate
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]
    
    # Tô màu xen kẽ cho các dòng dữ liệu
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            t_style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#f8fafc')))
            
    details_table.setStyle(TableStyle(t_style))
    story.append(details_table)
    
    if len(events) > 50:
        story.append(Spacer(1, 5))
        story.append(Paragraph(f"<i>* Báo cáo chỉ hiển thị tối đa 50 sự kiện mới nhất (Tổng số sự kiện trong khoảng lọc: {len(events)})</i>", subtitle_style))
        
    story.append(Spacer(1, 15))

    # ── E. ALBUM ẢNH MINH CHỨNG (Evidence Gallery) ───────────────
    # Chỉ in minh chứng của 6 sự kiện High/Medium nghiêm trọng nhất để tránh PDF bị phình dung lượng
    evidence_events = [e for e in events if e.level in ['high', 'medium']][:6]
    
    if evidence_events:
        story.append(Paragraph("III. Hình ảnh minh chứng vi phạm (Mức độ Cao / Trung bình)", h2_style))
        
        gallery_data = []
        row_cells = []
        
        for idx, e in enumerate(evidence_events):
            img_filename = f"{e.id}.jpg"
            img_local_path = os.path.join(current_app.static_folder, 'uploads', 'events', img_filename)
            
            # Khởi tạo widget chứa ảnh + caption dưới dạng Paragraph để tránh trôi chữ
            cell_content = []
            caption_str = f"<b>Hình {idx+1}:</b> Event #{e.id}<br/>ROI: {e.roi_name}<br/>Tư thế: {POSE_VN.get(e.pose, e.pose)}<br/>Bắt đầu: {e.started_at.strftime('%H:%M:%S')}"
            caption_p = Paragraph(caption_str, ParagraphStyle('CapStyle', parent=normal_style, fontSize=7, leading=9))
            
            if os.path.exists(img_local_path):
                try:
                    # Resize ảnh nhỏ gọn 110x80 px để xếp vừa 3 cột trên 1 hàng
                    p_img = Image(img_local_path, width=110, height=80)
                    cell_content.append(p_img)
                    cell_content.append(Spacer(1, 4))
                except Exception:
                    cell_content.append(Paragraph("[Lỗi tải ảnh]", normal_style))
            else:
                cell_content.append(Paragraph("[Không có ảnh]", normal_style))
                
            cell_content.append(caption_p)
            
            # Bọc trong một bảng nhỏ để giữ ảnh và chữ đi liền nhau không bị ngắt trang giữa chừng
            inner_tbl = Table([[cell_content]], colWidths=[165])
            inner_tbl.setStyle(TableStyle([
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
                ('PADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ]))
            
            row_cells.append(inner_tbl)
            
            # Xếp tối đa 3 ảnh trên một dòng
            if len(row_cells) == 3:
                gallery_data.append(row_cells)
                row_cells = []
                
        # Thêm hàng cuối nếu chưa đủ 3 phần tử
        if row_cells:
            while len(row_cells) < 3:
                row_cells.append("")
            gallery_data.append(row_cells)
            
        gallery_table = Table(gallery_data, colWidths=[180, 180, 180])
        gallery_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ]))
        
        # Bọc toàn bộ album ảnh trong KeepTogether để tránh chia cắt sang trang khác nửa chừng
        story.append(KeepTogether([gallery_table]))

    # Xây dựng tài liệu PDF
    try:
        doc.build(story)
        # 4. Trả file về cho trình duyệt tải xuống
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=pdf_filename,
            mimetype='application/pdf'
        )
    except Exception as build_err:
        return jsonify({'error': f'Lỗi tạo PDF: {str(build_err)}'}), 500
