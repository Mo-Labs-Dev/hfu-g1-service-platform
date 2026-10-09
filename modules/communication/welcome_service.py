from __future__ import annotations

import argparse

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient


class WelcomeService:
    """Visitor welcome service using the G1 built-in speaker."""

    WELCOME_MESSAGE = (
        "Hello! Welcome to the Institute of Product "
        "and Service Engineering at Furtwangen University. "
        "I am G1, your humanoid lab assistant. "
        "Today, I can introduce our laboratory, "
        "assist visitors, and demonstrate our research. "
        "Would you like to explore our lab?"
    )

    def __init__(self, interface: str = "enP2p1s0"):
        ChannelFactoryInitialize(0, interface)

        self.audio = AudioClient()
        self.audio.SetTimeout(10.0)
        self.audio.Init()

    def speak(self, message: str) -> None:
        if not message.strip():
            raise ValueError("Speech message cannot be empty")

        code = self.audio.TtsMaker(message, 1)
        print("TTS result:", code)

        if code not in (0, None):
            raise RuntimeError(f"TTS request failed: {code}")

    def welcome_visitor(self) -> None:
        self.speak(self.WELCOME_MESSAGE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Trigger the welcome message",
    )
    args = parser.parse_args()

    if args.demo:
        service = WelcomeService()
        service.welcome_visitor()
    else:
        print("WelcomeService ready. Use --demo to speak.")