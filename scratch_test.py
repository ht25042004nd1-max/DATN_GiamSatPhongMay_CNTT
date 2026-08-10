import sys
import os
import cv2
import json

sys.path.insert(0, r'd:\Documents\DATN\DATN_GiamSatPhongMay_CNTT')

from app.services.camera_service import ClientCamera

cam = ClientCamera()
cam.start(enable_pose=True)

# Feed a blank frame
frame = cv2.imread(r'd:\Documents\DATN\DATN_GiamSatPhongMay_CNTT\app\static\sample\sample_frame.jpg')
if frame is None:
    import numpy as np
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

cam.update_frame(frame)

import time
time.sleep(2) # wait for process

status = cam.get_status()
print(status)
try:
    json.dumps(status)
    print("JSON Serialize SUCCESS")
except Exception as e:
    print("JSON Serialize FAILED:", e)

cam.stop()
