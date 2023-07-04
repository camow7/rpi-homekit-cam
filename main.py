"""Implementation of a HAP Camera
Modifications for current system:
FILE_SNAPSHOT   = '/tmp/snapshot.jpg'
FILE_PERSISTENT = '/var/lib/hap-python/accessory.state'
DEV_VIDEO       = '/dev/video0'
SCALE		= '640x480'
IP_ADDRESS      = '192.168.1.2'

Note that the snapshot function adds a timestamp to the last image.
The font location has to be updated according to your system.
"""
import logging
import signal
import subprocess
import cv2

from pyhap.accessory_driver import AccessoryDriver
from pyhap import camera

logging.basicConfig(level=logging.INFO, format="[%(module)s] %(message)s")

FILE_SNAPSHOT   = './snapshot.jpg'
FILE_PERSISTENT = './accessory.state'
DEV_VIDEO       = '/dev/video0'
SCALE           = '1280x720'
DATE_CAPTION    = '%A %-d %B %Y, %X'
IP_ADDRESS      = '192.168.0.197'

# Specify the audio and video configuration that your device can support
# The HAP client will choose from these when negotiating a session.
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
            # Width, Height, framerate
            [320, 240, 15],  # Required for Apple Watch
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
    "start_stream_cmd":  (
      'ffmpeg -re -f video4linux2 -i ' + DEV_VIDEO + ' -threads 4 '
      '-vcodec h264_omx -an -pix_fmt yuv420p -r {fps} '
      '-b:v 2M -bufsize 2M '
      '-payload_type 99 -ssrc {v_ssrc} -f rtp '
      '-srtp_out_suite AES_CM_128_HMAC_SHA1_80 -srtp_out_params {v_srtp_key} '
      'srtp://{address}:{v_port}?rtcpport={v_port}&'
      'localrtcpport={v_port}&pkt_size=1316'),
}

class HAPCamera(camera.Camera):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.motion_detected = False
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2()
        self.is_running = True

    def motion_detection(self, frame):
        threshold = 500
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = self.background_subtractor.apply(gray)
        motion_area = cv2.countNonZero(mask)
        motion_detected = motion_area > threshold  # Set your desired threshold value
        if motion_detected and not self.motion_detected:
            print("Motion detected")
        elif not motion_detected and self.motion_detected:
            print("Motion stopped")
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
        cap = cv2.VideoCapture(0)  # Use the correct device ID for your camera

        while self.is_running:
            ret, frame = cap.read()

            if ret:
                self.motion_detection(frame)

                # Provide the frame as snapshot to HomeKit
                self.snapshot = frame

        cap.release()
        cv2.destroyAllWindows()

    def stop(self):
        self.is_running = False


# Start the accessory on port 51826
driver = AccessoryDriver(port=51826, persist_file=FILE_PERSISTENT)
acc = HAPCamera(options, driver, "Camera")
driver.add_accessory(accessory=acc)

# We want KeyboardInterrupts and SIGTERM (terminate) to be handled by the driver itself,
# so that it can gracefully stop the accessory, server and advertising.
signal.signal(signal.SIGTERM, driver.signal_handler)
# Start it!
driver.start()