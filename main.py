import logging
import signal
import subprocess
import cv2
import os

from pyhap.accessory_driver import AccessoryDriver
from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_SENSOR
from pyhap import camera
import datetime
import time

logging.basicConfig(level=logging.INFO, format="[%(module)s] %(message)s")

FILE_SNAPSHOT = './snapshot.jpg'
FILE_PERSISTENT = './accessory.state'
DEV_VIDEO = '/dev/video100'
SCALE = '1280x720'
DATE_CAPTION = '%A %-d %B %Y, %X'
IP_ADDRESS = '192.168.0.196'
IMAGE_DIR = '/home/camow7/rpi-homekit-cam/nas/stills'
VIDEO_DIR = '/home/camow7/rpi-homekit-cam/nas/video'

options = {
    "video": {
        "codec": {
            "profiles": [
                camera.VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["BASELINE"],
                camera.VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["MAIN"],
                camera.VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["HIGH"]
            ],
            "levels": [
                camera.VIDEO_CODEC_PARAM_LEVEL_TYPES['TYPE3_1'],
                camera.VIDEO_CODEC_PARAM_LEVEL_TYPES['TYPE3_2'],
                camera.VIDEO_CODEC_PARAM_LEVEL_TYPES['TYPE4_0'],
            ],
        },
        "resolutions": [
            [320, 240, 15],
            [1280, 720, 30],
        ],
    },
    "audio": {
        "codecs": [
            {
                'type': 'OPUS',
                'samplerate': 24,
            },
            {
                'type': 'AAC-eld',
                'samplerate': 16
            }
        ],
    },
    "srtp": True,
    "address": IP_ADDRESS,
    "start_stream_cmd": (
        'ffmpeg -re -f video4linux2 -i ' + DEV_VIDEO + ' -threads 4 '
        '-vcodec h264_v4l2m2m -an -pix_fmt yuv420p -r {fps} '
        '-b:v 2M -bufsize 2M '
        '-payload_type 99 -ssrc {v_ssrc} -f rtp '
        '-srtp_out_suite AES_CM_128_HMAC_SHA1_80 -srtp_out_params {v_srtp_key} '
        'srtp://{address}:{v_port}?rtcpport={v_port}&'
        'localrtcpport={v_port}&pkt_size=1316'),
}


class HAPCamera(camera.Camera, Accessory):
    
    category = CATEGORY_SENSOR  # Specify as a sensor category device
    def __init__(self, options, driver, name):
        Accessory.__init__(self, driver, name)
        camera.Camera.__init__(self, options, driver, name)

        self.motion_detected = False
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2()
        self.is_running = True
        self.cap = None  # Add this line to initialize self.cap
        self.recording_process = None  # ffmpeg process for recording
        self.net = cv2.dnn.readNetFromTensorflow('Object_Detection_Files/frozen_inference_graph.pb', 'Object_Detection_Files/ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt')

        # Create a Motion Sensor service
        serv_motion = self.add_preload_service('MotionSensor')
        self.char_detected = serv_motion.configure_char('MotionDetected')

    def start_recording(self, filename):
        cmd = [
            'ffmpeg', '-f', 'video4linux2', '-i', DEV_VIDEO,
            '-c:v', 'h264_v4l2m2m',  # H.264 video codec
            '-t', '00:01:00',  # Set recording time to 10 seconds
            filename
        ]
        self.recording_process = subprocess.Popen(cmd)
    
    # New method to stop recording
    def stop_recording(self):
        if self.recording_process:
            self.recording_process.terminate()
            self.recording_process = None

    def delete_old_videos(self):
        current_time = time.time()
        for video_file in os.listdir(VIDEO_DIR):
            file_path = os.path.join(VIDEO_DIR, video_file)
            file_age = current_time - os.path.getctime(file_path)  # File age in seconds
            if file_age > 30 * 24 * 60 * 60:  # 30 days in seconds
                os.remove(file_path)
                print(f"Deleted old video: {file_path}")

    def delete_old_images(self):  # New method
        current_time = time.time()
        for image_file in os.listdir(IMAGE_DIR):
            file_path = os.path.join(IMAGE_DIR, image_file)
            file_age = current_time - os.path.getctime(file_path)  # File age in seconds
            if file_age > 30 * 24 * 60 * 60:  # 30 days in seconds
                os.remove(file_path)
                print(f"Deleted old image: {file_path}")

    def motion_detection(self, frame):
        h, w, _ = frame.shape
        blob = cv2.dnn.blobFromImage(frame, 1.0 / 127.5, (300, 300), (127.5, 127.5, 127.5), swapRB=True, crop=False)
        self.net.setInput(blob)
        detections = self.net.forward()

        motion_detected = False

        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > 0.5:
                class_id = int(detections[0, 0, i, 1])
                # If you want to be specific about the detected object (e.g., person), you can check class_id.
                # For example, in COCO dataset, class_id = 1 typically means "person".
                # You can expand this to detect more object types if needed.
                if class_id == 1:
                    motion_detected = True
                    break

        if motion_detected and not self.motion_detected:
            print("Motion detected")
            self.char_detected.set_value(True)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{IMAGE_DIR}/{timestamp}.jpg"
            cv2.imwrite(filename, frame)
            #print(os.listdir('./nas'))
        elif not motion_detected and self.motion_detected:
            print("Motion stopped")
            self.char_detected.set_value(False)

        self.motion_detected = motion_detected


    def get_snapshot(self, image_size):
        cmd = [
            'ffmpeg', '-f', 'video4linux2', '-i', DEV_VIDEO,
            '-update', '1', '-y', '-vframes', '1',
            '-vf', 'scale=' + SCALE, '-q:v', '2',
            FILE_SNAPSHOT,
        ]
        returncode = subprocess.run(cmd)
        with open(FILE_SNAPSHOT, 'rb') as fp:
            return fp.read()

    def run(self):
        last_cleanup = 0
        self.cap = cv2.VideoCapture(DEV_VIDEO, apiPreference=cv2.CAP_V4L2)
        
        while self.is_running:
            ret, frame = self.cap.read()

            # Check for old videos and images once a day
            current_time = time.time()
            if current_time - last_cleanup > 24 * 60 * 60:  # 24 hours in seconds
                self.delete_old_videos()
                self.delete_old_images()  # Call the new method here
                last_cleanup = current_time
            
            if ret:
                self.motion_detection(frame)
                self.snapshot = frame

            # Check if the ffmpeg process is done (10 seconds has passed)
            if self.recording_process and self.recording_process.poll() is not None:
                self.stop_recording()
                
                # Start a new recording
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                video_filename = f"{VIDEO_DIR}/{timestamp}_video.mp4"
                self.start_recording(video_filename)

        self.cap.release()
        cv2.destroyAllWindows()

    def stop(self):
        self.stop_recording()  # Ensure the recording process is stopped
        self.is_running = False
        if self.cap is not None:
            self.cap.release()

if __name__ == "__main__":
    driver = AccessoryDriver(port=51826, persist_file=FILE_PERSISTENT)
    
    # Start the initial recording when the program starts
    acc = HAPCamera(options, driver, "Camera")
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    video_filename = f"{VIDEO_DIR}/{timestamp}_video.mp4"
    acc.start_recording(video_filename)

    driver.add_accessory(accessory=acc)
    signal.signal(signal.SIGTERM, driver.signal_handler)
    driver.start()
