# rpi-homekit-cam
 This software will turn a raspberry pi with USB camera into a Homekit security camera

 ## Setup Dependencies
 Follow these steps to setup the pi:

 1. Make sure python is installed and git
 1. Git clone this repo
 1. install kernel headers - ` sudo apt install raspberrypi-kernel-headers`
 1. Install OpenCV for python - `sudo apt install python3-opencv`. I don't have this in my pip requirements as I have the "wheel" fails often.
 1. Install Python HAP deps - `$ sudo apt-get install libavahi-compat-libdnssd-dev`
 1. install FFMPEG - `sudo apt install -y ffmpeg` ([Issue](#ffmpeg-with-bookworm))
 1. Install v4l2 for video loop back - `sudo apt-get install v4l2loopback-dkms` and `sudo apt-get install v4l-utils`
 1. enable at boot - `/etc/modules-load.d/v4l2loopback.conf` and add `v4l2loopback`
 1. Complete [Copying Camera Stream](#copying-camera-stream)
 1. cd into repo folder
 1. install python deps. - `pip install -r requirements.txt`

 ## Run
 1. `sudo modprobe v4l2loopback video_nr=99,100`
 1. `ffmpeg -f video4linux2 -i /dev/video0 -vcodec copy -f v4l2 /dev/video100`
 1. open second terminal and cd into git repo then run `python3 ./main.py`

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


## Troubleshooting
### ffmpeg with bookworm
```
cat << '_EOF_' > /etc/apt/preferences.d/dietpi-ffmpeg
Package: ffmpeg* libav* libpostproc* libsw*
Pin: origin archive.raspberrypi.org
Pin-Priority: -1
_EOF_
apt update
apt install ffmpeg
ffmpeg -version
```