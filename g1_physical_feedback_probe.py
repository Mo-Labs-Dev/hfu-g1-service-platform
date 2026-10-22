import time
import json
import threading

from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize,
    ChannelSubscriber,
)
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import SportModeState_


latest = None
received = threading.Event()


def callback(msg):
    global latest

    latest = {
        "velocity": list(msg.velocity),
        "yaw_speed": float(msg.yaw_speed),
        "position": list(msg.position),
    }

    received.set()


def main():
    ChannelFactoryInitialize(0, "enP2p1s0")

    subscriber = ChannelSubscriber(
        "rt/sportmodestate",
        SportModeState_,
    )

    subscriber.Init(callback, 10)

    print("Waiting for physical G1 motion feedback...")

    if received.wait(timeout=8):
        print(json.dumps(latest, indent=2))
    else:
        print("No SportModeState feedback received.")

    time.sleep(0.5)


if __name__ == "__main__":
    main()
