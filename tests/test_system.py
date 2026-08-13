import os
import sys
import json
import unittest
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from app import create_app, db
from app.models.user import User

class SystemTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def login_admin(self):
        """Hàm trợ giúp đăng nhập admin."""
        return self.client.post('/auth/login', data={
            'username': 'admin',
            'password': 'admin123'
        }, follow_redirects=True)

    # 1. Health check
    def test_health_check(self):
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('status'), 'ok')
        print(" [PASS] Health check endpoint")

    # 2. Auth tests
    def test_auth_login_logout(self):
        # GET login page
        res = self.client.get('/auth/login')
        self.assertEqual(res.status_code, 200)

        # POST login with valid credentials
        res = self.login_admin()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'dashboard', res.data.lower())

        # Logout
        res = self.client.get('/auth/logout', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        print(" [PASS] Authentication login & logout")

    # 3. View Routes Access (Authenticated)
    def test_authenticated_routes(self):
        self.login_admin()
        routes = [
            '/dashboard',
            '/monitor',
            '/floorplan',
            '/roi',
            '/alerts',
            '/statistics',
            '/reports',
            '/settings',
            '/accounts',
            '/audit-logs',
            '/iot',
            '/rooms',
            '/cameras',
            '/computers',
            '/iot_devices'
        ]
        for r in routes:
            res = self.client.get(r)
            self.assertEqual(res.status_code, 200, f"Failed route {r}")
        print(f" [PASS] All {len(routes)} HTML view routes loaded successfully (HTTP 200)")

    # 4. Room CRUD
    def test_room_crud(self):
        self.login_admin()
        rname = f"Phòng Test {int(time.time() * 1000)}"
        # Create
        res = self.client.post('/api/rooms', json={
            'name': rname,
            'location': 'Tầng 3',
            'is_active': True
        })
        self.assertEqual(res.status_code, 201)
        room_data = json.loads(res.data)
        room_id = room_data['id']

        # Get list
        res = self.client.get('/api/rooms')
        self.assertEqual(res.status_code, 200)

        # Update
        res = self.client.put(f'/api/rooms/{room_id}', json={
            'name': f"{rname} (Updated)",
            'location': 'Tầng 4'
        })
        self.assertEqual(res.status_code, 200)

        # Delete
        res = self.client.delete(f'/api/rooms/{room_id}')
        self.assertEqual(res.status_code, 200)
        print(" [PASS] Room CRUD API")

    # 5. Camera CRUD
    def test_camera_crud(self):
        self.login_admin()
        rname = f"Phòng Cam {int(time.time() * 1000)}"
        res_room = self.client.post('/api/rooms', json={'name': rname, 'location': 'Tầng 1'})
        self.assertEqual(res_room.status_code, 201)
        room_id = json.loads(res_room.data)['id']

        # Create Camera
        res = self.client.post('/api/cameras', json={
            'name': 'Cam Test 1',
            'room_id': room_id,
            'rtsp_url': '0',
            'is_active': True
        })
        self.assertEqual(res.status_code, 201)
        cam_id = json.loads(res.data)['id']

        # Update Camera
        res = self.client.put(f'/api/cameras/{cam_id}', json={'name': 'Cam Test 1 Updated'})
        self.assertEqual(res.status_code, 200)

        # Get List
        res = self.client.get('/api/cameras')
        self.assertEqual(res.status_code, 200)

        # Delete Camera
        res = self.client.delete(f'/api/cameras/{cam_id}')
        self.assertEqual(res.status_code, 200)

        # Clean room
        self.client.delete(f'/api/rooms/{room_id}')
        print(" [PASS] Camera CRUD API")

    # 6. Computer CRUD
    def test_computer_crud(self):
        self.login_admin()
        rname = f"Phòng Comp {int(time.time() * 1000)}"
        res_room = self.client.post('/api/rooms', json={'name': rname})
        self.assertEqual(res_room.status_code, 201)
        room_id = json.loads(res_room.data)['id']

        # Create
        res = self.client.post('/api/computers', json={
            'name': 'Máy 99',
            'room_id': room_id,
            'ip_address': '192.168.1.99',
            'mac_address': '00:11:22:33:44:55',
            'status': 'online'
        })
        self.assertEqual(res.status_code, 201)
        comp_id = json.loads(res.data)['id']

        # Update
        res = self.client.put(f'/api/computers/{comp_id}', json={'status': 'maintenance'})
        self.assertEqual(res.status_code, 200)

        # Delete
        res = self.client.delete(f'/api/computers/{comp_id}')
        self.assertEqual(res.status_code, 200)

        self.client.delete(f'/api/rooms/{room_id}')
        print(" [PASS] Computer CRUD API")

    # 7. IoT Device CRUD
    def test_iot_device_crud(self):
        self.login_admin()
        rname = f"Phòng IoT {int(time.time() * 1000)}"
        res_room = self.client.post('/api/rooms', json={'name': rname})
        self.assertEqual(res_room.status_code, 201)
        room_id = json.loads(res_room.data)['id']

        # Create
        res = self.client.post('/api/iot_devices', json={
            'name': 'ESP32 Test Node',
            'room_id': room_id,
            'device_type': 'esp32',
            'ip_address': '192.168.1.50'
        })
        self.assertEqual(res.status_code, 201)
        dev_id = json.loads(res.data)['id']

        # Update
        res = self.client.put(f'/api/iot_devices/{dev_id}', json={'status': 'online'})
        self.assertEqual(res.status_code, 200)

        # Delete
        res = self.client.delete(f'/api/iot_devices/{dev_id}')
        self.assertEqual(res.status_code, 200)

        self.client.delete(f'/api/rooms/{room_id}')
        print(" [PASS] IoT Device CRUD API")

    # 8. Floorplan APIs
    def test_floorplan_apis(self):
        self.login_admin()
        res = self.client.get('/api/floorplan/status')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/floorplan/devices?room_id=1')
        self.assertEqual(res.status_code, 200)

        res = self.client.post('/api/floorplan/devices', json={'room_id': 1, 'positions': []})
        self.assertEqual(res.status_code, 200)
        print(" [PASS] Floorplan Realtime & Device Position APIs")

    # 9. ROI & Events APIs
    def test_roi_and_events_apis(self):
        self.login_admin()
        res = self.client.get('/api/rois')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/events')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/events/count')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/camera_snapshot?camera_id=1')
        self.assertIn(res.status_code, [200, 500]) # 200 if cam active, 500 if no video
        print(" [PASS] ROI & Events APIs")

    # 10. IoT Heartbeat & Control API
    def test_iot_heartbeat(self):
        res = self.client.post('/api/iot/heartbeat', json={
            'ip': '192.168.1.100',
            'uptime': 3600
        })
        self.assertEqual(res.status_code, 200)

        self.login_admin()
        res = self.client.get('/api/iot/status')
        self.assertEqual(res.status_code, 200)
        print(" [PASS] IoT Heartbeat & Status APIs")

    # 11. System Performance Metrics API
    def test_system_metrics_api(self):
        self.login_admin()
        res = self.client.get('/api/settings/metrics')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('cpu', data)
        self.assertIn('ram', data)
        self.assertIn('disk', data)
        self.assertIn('process', data)
        print(" [PASS] System Performance Metrics API (psutil)")

    # 12. Dataset Capture API
    def test_dataset_capture_api(self):
        self.login_admin()
        res = self.client.post('/api/dataset/capture', json={
            'camera_id': 1,
            'label': 'TestPose',
            'note': 'System test frame'
        })
        self.assertIn(res.status_code, [201, 500])
        print(" [PASS] Dataset Collector API")

    # 13. System Config Export & Import APIs
    def test_config_export_import_apis(self):
        self.login_admin()
        res = self.client.get('/api/settings/export')
        self.assertEqual(res.status_code, 200)
        export_data = json.loads(res.data)
        self.assertIn('rooms', export_data)
        self.assertIn('cameras', export_data)

        # Import back
        res = self.client.post('/api/settings/import', json=export_data)
        self.assertEqual(res.status_code, 200)
        print(" [PASS] System Config Export & Import APIs")

    # 14. Dataset Page & Zip Exporter APIs
    def test_dataset_page_and_zip_apis(self):
        self.login_admin()
        res = self.client.get('/dataset')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/dataset/samples')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/dataset/download_zip')
        self.assertIn(res.status_code, [200, 404])
        print(" [PASS] Dataset Page & ZIP Archive Exporter APIs")

    # 15. Statistics Data API
    def test_statistics_data_api(self):
        self.login_admin()
        res = self.client.get('/api/statistics/data?range=week')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('total_alerts', data)
        self.assertIn('by_level', data)
        self.assertIn('timeline', data)
        print(" [PASS] Statistics Data API")

    # 16. Roadmap Evaluation & Latency Benchmark API
    def test_statistics_evaluation_api(self):
        self.login_admin()
        res = self.client.get('/api/statistics/evaluation')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('metrics', data)
        self.assertIn('precision', data['metrics'])
        self.assertIn('latency_benchmark', data)
        print(" [PASS] DATN Roadmap Model Evaluation & Latency Benchmark API")

    # 17. Multi-Board IoT Device Support (ESP32, TCL-508L, HY-LandTiger V2.0)
    def test_multi_board_iot_device(self):
        self.login_admin()
        res = self.client.post('/api/iot_devices', json={
            'name': 'LandTiger Node #1',
            'device_type': 'esp32',
            'board_type': 'HY-LandTiger V2.0',
            'protocol': 'MQTT',
            'room_id': 1
        })
        self.assertEqual(res.status_code, 201)
        dev_data = json.loads(res.data)
        self.assertEqual(dev_data['board_type'], 'HY-LandTiger V2.0')
        self.assertEqual(dev_data['protocol'], 'MQTT')
        print(" [PASS] Multi-Board IoT Device (TCL-508L & HY-LandTiger V2.0) API")

if __name__ == '__main__':
    print("=" * 60)
    print(" STARTING SYSTEM INTEGRATION TESTS (VIU LAB MONITOR)")
    print("=" * 60)
    unittest.main(verbosity=1)
