LiDAR
-in Docker
 source /opt/ros/humble/setup.bash
source /root/yahboomcar_ros2_ws/software/library_ws/install/setup.bash

export ROS_DOMAIN_ID=61
export ROS_LOCALHOST_ONLY=0
export FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_udp.xml

echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
ROS_DOMAIN_ID=61
root@raspberrypi:/# ros2 run ydlidar_ros2_driver ydlidar_ros2_driver_node \
  --ros-args \
  --params-file /root/yahboomcar_ros2_ws/software/library_ws/src/ydlidar_ros2_driver-humble/params/TminiPro.yaml

Open robot_menu.py
-in ssh pi@172.20.10.3
cd /home/pi/plate_billing_trial
source .venv/bin/activate
python3 robot_menu.py



plate_checkout.py = Detect plates & create bill show on Terminal [2]
robot_menu.py = menu control robot [1] Say Welcome(maybe drift in here), [3] call queue by queue_number.txt
scan_plate_360.py = Scan plate 360 & go ahead to the plate [4]