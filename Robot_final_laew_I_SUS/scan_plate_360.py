#!/usr/bin/env python3
"""ROSMASTER M1: search with camera while turning, approach a plate, stop.

No billing code is called here. ROS 2 Humble /scan and /cmd_vel required.
This is a conservative starting implementation, not a substitute for checking
real robot dimensions and LiDAR mount before physical operation.
"""
import argparse
import math
import threading
import time

import cv2
from ultralytics import YOLO
import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


def clamp(value, lo, hi):
    return min(hi, max(lo, value))


class Vision(threading.Thread):
    def __init__(self, model, camera, classes, conf):
        super().__init__(daemon=True)
        self.model_path = model
        self.camera = camera
        self.classes = {x.strip().lower() for x in classes.split(',') if x.strip()}
        self.conf = conf
        self.lock = threading.Lock()
        self.target = None  # (bearing radians, last seen timestamp, class)
        self.locked_name = None
        self.error = None
        self.stop_event = threading.Event()

    def get(self):
        with self.lock:
            return self.target

    def lock_name(self, name):
        with self.lock:
            self.locked_name = name

    def run(self):
        cap = None
        try:
            model = YOLO(self.model_path)
            source = int(self.camera) if self.camera.isdigit() else self.camera
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                raise RuntimeError('Cannot open camera ' + self.camera)
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                result = model.predict(frame, conf=self.conf, imgsz=640, verbose=False)[0]
                h, w = frame.shape[:2]
                candidates = []
                for b in result.boxes:
                    name = str(model.names[int(b.cls[0])]).lower()
                    if name not in self.classes or (
                        self.locked_name is not None
                        and name != self.locked_name
                    ):
                        continue
                    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
                    area = (x2-x1)*(y2-y1)
                    # Prefer the most centered plate, then the larger detection.
                    cx = (x1+x2)/2
                    candidates.append((abs(cx/w-0.5), -area, cx, name))
                with self.lock:
                    if candidates:
                        _, _, cx, name = min(candidates)
                        # 60-degree horizontal field of view: camera calibration needed.
                        bearing = -((cx/w)-0.5)*math.radians(60)
                        self.target = (bearing, time.monotonic(), name)
                    else:
                        self.target = None
        except Exception as exc:
            self.error = str(exc)
        finally:
            if cap is not None:
                cap.release()


class Robot(Node):
    def __init__(self, args):
        super().__init__('scan_plate_360')
        self.args = args
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.sub = self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.last_scan = 0.0
        self.front = None
        self.turn_clear = False
        self.state = 'SCAN'
        self.started = time.monotonic()
        self.last_tick = self.started
        self.turn_accum = 0.0
        self.seen_count = 0
        self.selected_name = None
        self.confirm_stamp = None
        self.confirm_started = 0.0
        self.missing_since = None
        self.vision = None
        self.last_report = 0.0
        self.speed = [0.0, 0.0]
        self.approach_reference = None

    def on_scan(self, msg):
        pts = []
        a = msg.angle_min
        for d in msg.ranges:
            if (math.isfinite(d) and max(msg.range_min, 0.03) <= d <= min(msg.range_max, 6.0)):
                x = d * math.cos(a)
                y = d * math.sin(a)
                # Robot body estimates: 30 x 25 cm, LiDAR assumed centered.
                if not(abs(x) < 0.15 and abs(y) < 0.125):
                    pts.append((x, y))
            a += msg.angle_increment
        # Keep LiDAR points for target-directed distance measurement.
        self.scan_points = pts
        self.front = None
        # Do not rotate if a return lies within the swept body radius + 5cm.
        self.turn_clear = all(math.hypot(x,y) >= math.hypot(0.15,0.125)+0.05 for x,y in pts)
        self.last_scan = time.monotonic()

    def front_gap_to_target(self, bearing):
        if not hasattr(self, "scan_points"):
            return None

        target_gaps = []
        safety_gaps = []

        for x, y in self.scan_points:
            if x <= 0.15:
                continue

            gap = x - 0.15

            # ตรวจพื้นที่ที่ตัวรถต้องเคลื่อนผ่าน
            if abs(y) <= 0.175:
                safety_gaps.append(gap)

            # วัดระยะเป้าหมายจากแนวมุมที่กล้องเห็นจาน
            angle = math.atan2(y, x)
            diff = (angle - bearing + math.pi) % (2 * math.pi) - math.pi

            if abs(diff) <= math.radians(8):
                target_gaps.append(gap)

        if not target_gaps or not safety_gaps:
            return None

        # ใช้ระยะเป้าหมาย แต่ไม่มองข้ามวัตถุในทางรถ
        return min(min(target_gaps), min(safety_gaps))

    def command(self, linear, angular):
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self.pub.publish(msg)

    def stop(self):
        self.speed = [0.,0.]
        for _ in range(5):
            self.command(0.,0.)
            time.sleep(0.03)

    def tick(self, target, vision_error):
        now = time.monotonic()
        dt = min(now-self.last_tick, 0.2)
        self.last_tick = now
        if vision_error:
            print('CAMERA/YOLO ERROR:', vision_error, flush=True)
            return False
        if now-self.last_scan > 0.6:
            self.command(0,0)
            if now-self.started > 8:
                print('STOP: no fresh LiDAR scan', flush=True)
                return False
            return True
        if now-self.started > self.args.timeout:
            print('STOP: time limit', flush=True)
            return False
        bearing = None
        name = None
        if target is not None and now-target[1] < 0.8:
            bearing, _, name = target
        if self.state == 'SCAN':
            if bearing is not None:
                self.selected_name = name
                self.vision.lock_name(name)
                self.seen_count = 1
                self.confirm_stamp = target[1]
                self.confirm_started = now
                self.state = 'CONFIRM'
                self.command(0, 0)
                print('FOUND:', name, '- STOP ROTATING', flush=True)
                return True

            if self.turn_accum >= 2 * math.pi:
                self.command(0, 0)
                print('STOP: completed search; no plate found', flush=True)
                return False

            omega = 0.15
            self.command(0, omega)
            self.turn_accum += omega * dt
            return True

        if self.state == 'CONFIRM':
            self.command(0, 0)

            if (bearing is not None
                    and name == self.selected_name
                    and target[1] != self.confirm_stamp):
                self.confirm_stamp = target[1]
                self.seen_count += 1

            if self.seen_count >= 2:
                print('TARGET LOCKED:', self.selected_name, flush=True)
                self.state = 'ALIGN'
                return True

            if now - self.confirm_started > 2.0:
                print('Detection not confirmed - resume scanning', flush=True)
                self.selected_name = None
                self.vision.lock_name(None)
                self.state = 'SCAN'
            return True

        if self.state == 'ALIGN':
            if bearing is None:
                self.command(0, 0)

                if self.missing_since is None:
                    self.missing_since = now

                # Stop and wait for fresh camera frames first.
                if now - self.missing_since >= 1.2:
                    self.state = 'REACQUIRE'
                    self.reacquire_started = now
                    self.reacquire_hits = 0
                    self.reacquire_seen_stamp = None
                    print('REACQUIRING LOCKED TARGET', flush=True)
                return True

            self.missing_since = None

            # Turn slowly to centre the detected plate.
            if abs(bearing) > math.radians(4):
                omega = clamp(0.65 * bearing, -0.08, 0.08)
                self.command(0, omega)
                return True

            self.command(0, 0)
            self.state = 'APPROACH'
            print('ALIGNED - APPROACHING:', name, flush=True)
            return True

        if self.state == 'REACQUIRE':
            # Never drive forward during target recovery.
            self.command(0, 0)

            if bearing is not None:
                # Confirm using two distinct camera frames.
                if target[1] != self.reacquire_seen_stamp:
                    self.reacquire_seen_stamp = target[1]
                    self.reacquire_hits += 1

                if self.reacquire_hits >= 2:
                    self.state = 'ALIGN'
                    self.missing_since = None
                    self.command(0, 0)
                    print('TARGET REACQUIRED:', name, flush=True)
                return True

            self.reacquire_hits = 0
            self.reacquire_seen_stamp = None
            elapsed = now - self.reacquire_started

            if elapsed >= 5.0:
                self.command(0, 0)
                print('STOP: target not visible after retry', flush=True)
                return False

            # Small, slow left-right sweep.
            if elapsed < 1.2:
                omega = 0.05
            elif elapsed < 3.6:
                omega = -0.05
            else:
                omega = 0.05

            self.command(0, omega)
            return True

        if self.state == 'APPROACH':
            if bearing is not None and abs(bearing) > math.radians(4):
                self.command(0, 0)
                self.state = 'ALIGN'
                return True

            if bearing is not None:
                self.front = self.front_gap_to_target(bearing)
            if bearing is None:
                self.command(0,0)
                self.state = 'ALIGN'
                return True
            if self.front is not None:
                if self.approach_reference is None:
                    self.approach_reference = self.front
                self.approach_reference = min(self.approach_reference, self.front)

            if self.front is None:
                self.command(0, 0)
                print('STOP: no distance data', flush=True)
                return False

            if self.front < self.args.stop_gap - 0.08:
                self.command(0, 0)
                print('STOP: obstacle too close, not arrived', flush=True)
                return False

            if self.front <= self.args.stop_gap + 0.05:
                self.command(0, 0)
                print('REACHED STOP DISTANCE. Select [2] to bill.', flush=True)
                return False
            if abs(bearing) > math.radians(18):
                self.command(0,0)
                self.state = 'ALIGN'
                return True
            if not hasattr(self, 'last_safe_front'):
                self.last_safe_front = self.front

            if self.front > self.last_safe_front + 0.10:
                self.command(0, 0)
                print('STOP: unreliable target distance', flush=True)
                return False

            self.last_safe_front = min(self.last_safe_front, self.front)

            # Conservative speed, slow further as the bumper gets close.
            speed = clamp(0.08*(self.front-self.args.stop_gap)/0.35, 0.025, 0.08)
            if self.front < self.args.stop_gap+0.12:
                speed = min(speed, 0.035)
            self.command(speed, 0.0)  # do not rotate while driving beside obstacles
            if now-self.last_report > 2:
                print('APPROACH:', name, 'front gap %.2fm' % self.front, flush=True)
                self.last_report = now
        return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', default='/root/plate_trial/model/best.pt')
    p.add_argument('--camera', default='0')
    p.add_argument('--classes', default='Pink,Blue,Green,Yellow')
    p.add_argument('--conf', type=float, default=0.8)
    p.add_argument('--stop-gap', type=float, default=0.30)
    p.add_argument('--timeout', type=float, default=90)
    args = p.parse_args()
    vision = Vision(args.model,args.camera,args.classes,args.conf)
    rclpy.init()
    robot = Robot(args)
    robot.vision = vision
    vision.start()
    print('Searching for plates (up to 360 degrees). Ctrl+C to stop.', flush=True)
    try:
        while rclpy.ok():
            rclpy.spin_once(robot, timeout_sec=0.08)
            if not robot.tick(vision.get(), vision.error):
                break
    except KeyboardInterrupt:
        print('STOPPED by user', flush=True)
    finally:
        robot.stop()
        vision.stop_event.set()
        vision.join(timeout=3)
        robot.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
