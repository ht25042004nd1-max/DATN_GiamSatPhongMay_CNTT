# ============================================================
# app/services/system_service.py — Đo đạc hiệu năng hệ thống
# ============================================================
import os
import sys
import time
import threading
import psutil
from datetime import datetime

_start_time = time.time()

def get_system_metrics() -> dict:
    """
    Trả về chỉ số hiệu năng phần cứng thực tế của hệ thống:
    - CPU %, Số nhân CPU
    - RAM tổng, RAM đã dùng, % RAM
    - Disk tổng, Disk đã dùng, % Disk
    - RAM của riêng process Python này (MB)
    - Số lượng Threads đang chạy
    - Thời gian Uptime (giây & định dạng chuỗi)
    """
    process = psutil.Process(os.getpid())
    proc_memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True)
    
    virtual_mem = psutil.virtual_memory()
    # Tự detect đường dẫn đĩa cứng: Windows dùng 'C:\\', Linux dùng '/'
    disk_root = 'C:\\' if sys.platform.startswith('win') else '/'
    try:
        disk_mem = psutil.disk_usage(disk_root)
    except Exception:
        disk_mem = psutil.disk_usage('.')
    
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    return {
        'cpu': {
            'percent': cpu_percent,
            'cores': cpu_count
        },
        'ram': {
            'total_gb': round(virtual_mem.total / (1024**3), 2),
            'used_gb': round(virtual_mem.used / (1024**3), 2),
            'percent': virtual_mem.percent
        },
        'disk': {
            'total_gb': round(disk_mem.total / (1024**3), 2),
            'used_gb': round(disk_mem.used / (1024**3), 2),
            'percent': disk_mem.percent
        },
        'process': {
            'pid': os.getpid(),
            'memory_mb': proc_memory_mb,
            'active_threads': threading.active_count()
        },
        'uptime_seconds': uptime_seconds,
        'uptime_str': uptime_str,
        'timestamp': datetime.now().strftime('%H:%M:%S')
    }
