import logging
import signal
import subprocess
import cv2

from pyhap.accessory_driver import AccessoryDriver
from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_SENSOR
from pyhap import camera

logging.basicConfig(level=logging.INFO, format="[%(module)s] %(message)s")

FILE_SNAPSHOT = './snapshot.jpg'
FILE_PERSISTENT = './accessory.state'
DEV_VIDEO = '/dev/video100'
SCALE = '1280x720'
DATE_CAPTION = '%A %-d %B %Y, %X'
IP_ADDRESS = '192.168.0.196'

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
        '-vcodec h264_omx -an -pix_fmt yuv420p -r {fps} '
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

        # Create a Motion Sensor service
        serv_motion = self.add_preload_service('MotionSensor')
        self.char_detected = serv_motion.configure_char('MotionDetected')

    def motion_detection(self, frame):
        threshold = 500
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = self.background_subtractor.apply(gray)
        motion_area = cv2.countNonZero(mask)
        motion_detected = motion_area > threshold  # Set your desired threshold value
        if motion_detected and not self.motion_detected:
            print("Motion detected")
            self.char_detected.set_value(True)  # Notify HomeKit motion detected
        elif not motion_detected and self.motion_detected:
            print("Motion stopped")
            self.char_detected.set_value(False)  # Notify HomeKit motion stopped
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
        self.cap = cv2.VideoCapture("/dev/video100", apiPreference=cv2.CAP_V4L2)  # Use the correct device ID for your camera

        while self.is_running:
            ret, frame = self.cap.read()

            if ret:
                self.motion_detection(frame)

                # Provide the frame as snapshot to HomeKit
                self.snapshot = frame

        self.cap.release()
        cv2.destroyAllWindows()

    def stop(self):
        self.is_running = False
        if self.cap is not None:
            self.cap.release()


driver = AccessoryDriver(port=51826, persist_file=FILE_PERSISTENT)
acc = HAPCamera(options, driver, "Camera")
driver.add_accessory(accessory=acc)

signal.signal(signal.SIGTERM, driver.signal_handler)
driver.start()
