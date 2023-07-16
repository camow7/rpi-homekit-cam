# rpi-homekit-cam
 This software will turn a raspberry pi with USB camera into a Homekit security camera

## Setup Service
First open the `camera.service` file and make sure the path to `main.py` is correct for your system. Then run the command below.

```
sudo cp camera.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable camera.service
sudo systemctl start camera.service
```

## Installing Requirements
```
pip install -r requirements.txt
```

## Copying Camera Stream
To allow openCV to access the camera feed for motion while also allowing the HAP library to stream the camera we need to use ffmpeg to copy the video to a seperate file:

```
ffmpeg -f video4linux2 -i /dev/video0 -vcodec copy -f v4l2 /dev/video100
```

If you want to copy it to multiple video device use
```
ffmpeg -f video4linux2 -i /dev/video0 -vcodec copy -map 0 -f v4l2 /dev/video99 -vcodec copy -map 0 -f v4l2 /dev/video100
```

## Creating Extra Video Streams
1. `sudo apt-get install v4l2loopback-dkms`
1. `sudo nano /etc/modprobe.d/v4l2loopback.conf`
1. Add this so it creates extra video devices on boot `options v4l2loopback video_nr=99,100`
