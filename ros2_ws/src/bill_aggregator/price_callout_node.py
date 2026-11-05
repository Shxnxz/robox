#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32, String

class PriceCalloutNode(Node):
    def __init__(self):
        super().__init__('price_callout_node')

        # Subscribe to total price from plate detector
        self.price_sub = self.create_subscription(
            Int32,
            '/total_price',
            self.price_callback,
            10
        )

        # Publish text to Yahboom TTS
        # Common topics: /tts_text_input  or  /tts_text
        self.tts_pub = self.create_publisher(String, '/tts_text_input', 10)

        self.last_spoken = -1
        self.get_logger().info('Price Callout Node started')

    def price_callback(self, msg):
        total = msg.data

        # Avoid repeating the same total many times
        if total == self.last_spoken:
            return

        self.last_spoken = total

        # Create the spoken sentence
        # Change the language/style as needed
        text = f"Total is {total} baht."
        # Alternative examples:
        # text = f"The total price is {total}."
        # text = f"Your bill is {total} baht."
        # text = str(total)   # just the number

        self.get_logger().info(f'Speaking: {text}')

        tts_msg = String()
        tts_msg.data = text
        self.tts_pub.publish(tts_msg)

def main(args=None):
    rclpy.init(args=args)
    node = PriceCalloutNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
