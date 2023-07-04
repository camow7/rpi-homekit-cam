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