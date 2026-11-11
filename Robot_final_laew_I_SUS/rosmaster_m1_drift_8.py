#!/usr/bin/env python3
"""One smooth-ish figure-eight using ROS 2 /cmd_vel (open-loop)."""
import math
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


class FigureEight(Node):
    def __init__(self):
        super().__init__('rosmaster_m1_figure8')
        self.publisher = self.create_publisher(Twist, '/cmd_vel', 10)

        # ==== EDIT THESE ==== 
        self.declare_parameter('speed', 0.40)           # m/s, forward speed
        self.declare_parameter('radius', 0.30)          # m, target turn radius
        self.declare_parameter('transition_time', 0.8)  # s, smooth L->R
        self.declare_parameter('ramp_time', 0.8)        # s, accelerate/decelerate
        # ====================

        p = lambda name: float(self.get_parameter(name).value)
        self.speed = p('speed')
        self.radius = p('radius')
        self.transition = p('transition_time')
        self.ramp = p('ramp_time')
        if self.speed <= 0 or self.radius <= 0 or self.transition < 0 or self.ramp < 0:
            raise ValueError('speed/radius must be positive; times must be >= 0')

        self.omega = self.speed / self.radius
        self.loop_time = 2.0 * math.pi * self.radius / self.speed
        self.total = 2.0 * self.loop_time
        if self.transition >= self.loop_time:
            raise ValueError('transition_time must be smaller than one loop time')
        self.started = None
        self.finished = False
        self.timer = self.create_timer(0.05, self.tick)
        self.get_logger().info('Figure-eight: left loop -> right loop -> stop. Ctrl+C stops.')

    def tick(self):
        if self.finished:
            return
        if self.publisher.get_subscription_count() == 0:
            return
        if self.started is None:
            self.started = time.monotonic()
        t = time.monotonic() - self.started
        if t >= self.total:
            self.finished = True
            self.stop()
            self.timer.cancel()
            self.get_logger().info('Figure-eight complete.')
            return

        # Both lobes have similar duration; blend angular velocity through zero.
        if self.transition == 0:
            turn = 1.0 if t < self.loop_time else -1.0
        else:
            blend = smoothstep((t - (self.loop_time - self.transition / 2)) / self.transition)
            turn = 1.0 - 2.0 * blend

        # Smooth beginning/end. If the path deviates from a perfect 8, adjust radius.
        ramp_up = 1.0 if self.ramp == 0 else smoothstep(t / self.ramp)
        ramp_down = 1.0 if self.ramp == 0 else smoothstep((self.total - t) / self.ramp)
        scale = min(ramp_up, ramp_down)
        msg = Twist()
        msg.linear.x = self.speed * scale
        msg.angular.z = self.omega * turn * scale
        self.publisher.publish(msg)

    def stop(self):
        for _ in range(10):
            self.publisher.publish(Twist())
            time.sleep(0.05)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = FigureEight()
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.stop()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
