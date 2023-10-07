import logging
import signal
import subprocess
import cv2
import os
import numpy as np

from pyhap.accessory_driver import AccessoryDriver
from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_SENSOR
from pyhap import camera
import datetime
import time
import shutil

logging.basicConfig(level=logging.INFO, format="[%(module)s] %(message)s")

FILE_SNAPSHOT = './snapshot.jpg'
FILE_PERSISTENT = './accessory.state'
DEV_VIDEO = '/dev/video100'
SCALE = '1280x720'
DATE_CAPTION = '%A %-d %B %Y, %X'
IP_ADDRESS = '192.168.0.196'
IMAGE_DIR = '/home/camow7/rpi-homekit-cam/local/stills'
VIDEO_DIR = '/home/camow7/rpi-homekit-cam/local/video'
SECONDARY_DIR_VIDEO = '/home/camow7/rpi-homekit-cam/nas/cameras/garage/video'
SECONDARY_DIR_IMAGE = '/home/camow7/rpi-homekit-cam/nas/cameras/garage/stills'



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
        self.current_video_file_path = ""
        self.motion_detected = False
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2()
        self.is_running = True
        self.cap = None  # Add this line to initialize self.cap
        self.recording_process = None  # ffmpeg process for recording
        self.net = cv2.dnn.readNetFromTensorflow('Object_Detection_Files/frozen_inference_graph.pb', 'Object_Detection_Files/ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt')

        # Create a Motion Sensor service
        serv_motion = self.add_preload_service('MotionSensor')
        self.char_detected = serv_motion.configure_char('MotionDetected')
   
    #function that backs up to NAS
    def copy_to_secondary_directory(self, source_file_path, is_video=True):
        if is_video:
            rel_path = os.path.relpath(source_file_path, VIDEO_DIR)
            dest_path = os.path.join(SECONDARY_DIR_VIDEO, rel_path)
        else:
            rel_path = os.path.relpath(source_file_path, IMAGE_DIR)
            dest_path = os.path.join(SECONDARY_DIR_IMAGE, rel_path)

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(source_file_path, dest_path)

    def start_recording(self, filename):
        # Ensure the directory exists
        directory = os.path.dirname(filename)
        if not os.path.exists(directory):
            os.makedirs(directory)

        print("Full video path to write:", os.path.abspath(filename))
        print("Directory exists:", os.path.exists(directory))
        self.current_video_file_path = filename

        cmd = [
            'ffmpeg', '-f', 'video4linux2', '-i', DEV_VIDEO,
            '-c:v', 'h264_v4l2m2m',  # H.264 video codec
            '-t', '00:05:00',  # Set recording time 5 minutes
            filename
        ]
        self.recording_process = subprocess.Popen(cmd)

    
    # New method to stop recording
    def stop_recording(self):
        if self.recording_process:
            self.recording_process.terminate()
            self.recording_process = None
            self.copy_to_secondary_directory(self.current_video_file_path, is_video=True) 

    def delete_old_files_from_directory(self, directory):
        current_time = time.time()

        for root, dirs, files in os.walk(directory, topdown=False):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                file_age = current_time - os.path.getctime(file_path)
                
                if file_age > 30 * 24 * 60 * 60:  # 30 days in seconds
                    os.remove(file_path)
                    print(f"Deleted old file: {file_path}")

    def delete_old_videos(self):
        self.delete_old_files_from_directory(VIDEO_DIR)

    def delete_old_images(self):
        self.delete_old_files_from_directory(IMAGE_DIR)

    def sync_directories(self, primary_dir, secondary_dir):
        for root, _, files in os.walk(primary_dir):
            for file in files:
                primary_path = os.path.join(root, file)
                rel_path = os.path.relpath(primary_path, primary_dir)
                secondary_path = os.path.join(secondary_dir, rel_path)

                if not os.path.exists(secondary_path):
                    os.makedirs(os.path.dirname(secondary_path), exist_ok=True)
                    shutil.copy2(primary_path, secondary_path)
                    print(f"Copied missing file {primary_path} to {secondary_path}")



    def motion_detection(self, frame):
        h, w, _ = frame.shape
        blob = cv2.dnn.blobFromImage(frame, 1.0 / 127.5, (300, 300), (127.5, 127.5, 127.5), swapRB=True, crop=False)
        self.net.setInput(blob)
        detections = self.net.forward()

        motion_detected = False

        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > 0.6:
                class_id = int(detections[0, 0, i, 1])
                if class_id == 1:  # person
                    motion_detected = True

                    # Get the bounding box coordinates
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    (startX, startY, endX, endY) = box.astype("int")

                    # Draw the bounding box
                    cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 0, 255), 2)
                    break

        if motion_detected and not self.motion_detected:
            print("Motion detected")
            self.char_detected.set_value(True)
            timestamp = datetime.datetime.now()
            formatted_time = timestamp.strftime('%Y%m%d_%H%M%S')
            daily_dir = timestamp.strftime('%Y/%m/%d')
            
            daily_path = os.path.join(IMAGE_DIR, daily_dir)
            os.makedirs(daily_path, exist_ok=True)
            
            filename = f"{daily_path}/{formatted_time}.jpg"
            cv2.imwrite(filename, frame)
            self.copy_to_secondary_directory(filename, is_video=False)

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
                # Sync the directories before deleting old files
                self.sync_directories(VIDEO_DIR, SECONDARY_DIR_VIDEO)
                self.sync_directories(IMAGE_DIR, SECONDARY_DIR_IMAGE)
                self.delete_old_videos()
                self.delete_old_images()  # Call the new method here
                last_cleanup = current_time
            
            if ret:
                self.motion_detection(frame)
                self.snapshot = frame

            if self.recording_process and self.recording_process.poll() is not None:
                self.stop_recording()

                timestamp = datetime.datetime.now()
                formatted_time = timestamp.strftime('%Y%m%d_%H%M%S')
                daily_dir = timestamp.strftime('%Y/%m/%d')
                
                daily_path = os.path.join(VIDEO_DIR, daily_dir)
                os.makedirs(daily_path, exist_ok=True)
                
                video_filename = f"{daily_path}/{formatted_time}_video.mp4"
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
    timestamp = datetime.datetime.now()
    formatted_time = timestamp.strftime('%Y%m%d_%H%M%S')
    daily_dir = timestamp.strftime('%Y/%m/%d')
    
    daily_path = os.path.join(VIDEO_DIR, daily_dir)
    os.makedirs(daily_path, exist_ok=True)
    
    video_filename = f"{daily_path}/{formatted_time}_video.mp4"
    acc.start_recording(video_filename)

    driver.add_accessory(accessory=acc)
    signal.signal(signal.SIGTERM, driver.signal_handler)
    driver.start()
