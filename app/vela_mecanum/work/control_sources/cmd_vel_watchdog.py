#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cmd_vel 看门狗 —— 指令停了就自动停车。

背景：厂商的 odom_publisher_node 收到一条 cmd_vel 就直接下发一次电机指令，
**没有超时逻辑**。所以发指令的一方（遥控/脚本/语音助手/网络）一旦中断，
车会保持最后的速度一直跑下去 —— 这就是"运动不会自动停下"。

做法（不改厂商代码）：
  订阅厂商的三个速度入口 /controller/cmd_vel、/cmd_vel、/app/cmd_vel，
  只要 TIMEOUT 秒内没有新指令、且最后一次指令不是零速，就往
  /controller/cmd_vel 发一条零速度，由厂商节点转成电机停止。

  只发一次，避免刷屏；有新指令进来就重新计时。
"""
from __future__ import annotations

import time

import rclpy
from geometry_msgs.msg import Twist

TIMEOUT = 0.5      # 秒：超过这么久没有新指令就停车
HZ = 20.0          # 检查频率
TOPICS = ("/controller/cmd_vel", "/cmd_vel", "/app/cmd_vel")


class Watchdog:
    def __init__(self):
        self.node = rclpy.create_node("cmd_vel_watchdog")
        self.pub = self.node.create_publisher(Twist, "/controller/cmd_vel", 10)
        for topic in TOPICS:
            self.node.create_subscription(Twist, topic, self.on_cmd, 10)
        self.last_rx = 0.0
        self.moving = False
        self.stops = 0
        self.node.create_timer(1.0 / HZ, self.tick)
        self.node.get_logger().info(
            "cmd_vel 看门狗已启动：%.1f 秒没有新指令就发零速度停车" % TIMEOUT)

    def on_cmd(self, msg: Twist) -> None:
        self.last_rx = time.monotonic()
        self.moving = (abs(msg.linear.x) > 1e-3 or abs(msg.linear.y) > 1e-3
                       or abs(msg.angular.z) > 1e-3)

    def tick(self) -> None:
        if self.last_rx == 0.0 or not self.moving:
            return
        age = time.monotonic() - self.last_rx
        if age > TIMEOUT:
            self.pub.publish(Twist())      # 全零 = 停
            self.moving = False
            self.stops += 1
            self.node.get_logger().warn(
                "指令中断 %.1f 秒，已发零速度停车（累计 %d 次）" % (age, self.stops))


def main() -> int:
    rclpy.init()
    watchdog = Watchdog()
    try:
        rclpy.spin(watchdog.node)
    except KeyboardInterrupt:
        pass
    finally:
        watchdog.node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
