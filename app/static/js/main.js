// ============================================================
// static/js/main.js — JavaScript toàn cục cho dự án
// Logic JS chi tiết sẽ được thêm ở các giai đoạn sau
// ============================================================

console.log('✅ Lab Monitor System - Frontend loaded');

// Hàm format thời gian theo kiểu Việt Nam: dd/mm/yyyy HH:MM:SS
function formatDateTime(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleString('vi-VN');
}
