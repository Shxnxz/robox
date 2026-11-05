# 🍣 Plate-Pricing Robot (ROSMASTER M1)

A mobile robot that goes from table to table, spots the plates on each table, works out each plate's price from its color, and shows the bill on its front LCD. It's based on the plate-color pricing used at conveyor-belt sushi restaurants such as Sushiro Thailand.

Built on the **Yahboom ROSMASTER M1** (Raspberry Pi 5, ROS2 Humble) by a team of 8 university students.

> 🚧 Work in progress. This is a university project and not affiliated with Sushiro.

## How it works

```
Navigate to table → Stop → Pan camera → Detect plates → Classify color → Count & price → Show bill on LCD
```

| Stage | What happens |
|---|---|
| **Navigation** | Nav2 waypoint patrol on a LiDAR SLAM map. Tested in Gazebo first. |
| **Detection** | A YOLO nano model finds plates in each camera frame. |
| **Color classification** | One detection class per plate color, plus an HSV/CNN check to tell similar colors apart. |
| **Counting** | Results from several frames are combined so no plate is counted twice. |
| **Billing** | Color → price comes from a config file, then the robot computes the subtotal, service charge and total. The net will be audio voice call out |
| **Display** | The front LCD shows the count per color and the total in THB. If confidence is low, it shows "please check" instead. |

## Plate prices (default config)

| Color | Price (THB) |
|---|---|
| 🩵 Blue | 30 |
| 💚 Green | 40 |
| 🩷 Pink | 60 |
| 💛 Yellow | 80 |

Prices are stored in `config/plate_prices.yaml`, not in the model. To change them, edit the file; no retraining is needed.

## Repository structure

```
├── config/          # plate prices, camera & model settings
├── data/            # dataset manifests & labeling guide (images stored separately)
├── models/          # training scripts, exported ONNX/NCNN weights
├── ros2_ws/src/
│   ├── plate_detector/    # inference node → /plates/detections
│   ├── bill_aggregator/   # multi-frame counting → /bill/current
│   ├── lcd_display/       # renders the bill on the front LCD
│   ├── mission/           # table-scan state machine
│   └── bringup/           # launch files (sim + real robot)
├── sim/             # Gazebo restaurant world
└── docs/            # architecture, model card, test results
```

## Tech stack

ROS2 Humble · Nav2 · slam_toolbox · Gazebo · Ultralytics YOLO · OpenCV · ONNX / NCNN · Python

## Getting started

```bash
# Clone into your ROS2 workspace
git clone <repo-url> && cd <repo>/ros2_ws
rosdep install --from-paths src -y --ignore-src
colcon build && source install/setup.bash

# Run in simulation
ros2 launch bringup sim.launch.py

# Run on the robot
ros2 launch bringup robot.launch.py
```

## Team

| Role | Member |
|---|---|
| Project Lead & ROS2 Integration | |
| Data Collection | |
| Data Labeling & QA | |
| ML – Plate Detection | |
| ML – Color Classification & Pricing | |
| Edge Deployment | |
| Robotics & Navigation | |
| Display, Billing UI & QA | |
