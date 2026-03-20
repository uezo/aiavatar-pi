"""Whisplay motion client with preset hardware config.

ST7789 LCD (240x280) + WM8960 audio + GPIO button (pin 11).
"""

from ...button import GPIOButton
from ...display.st7789 import ST7789
from ..pi.motion_client import PiMotionClient


class WhisplayMotionClient(PiMotionClient):

    def __init__(self, *, backlight: int = 50, volume: int = 100, **kwargs):
        super().__init__(
            lcd=ST7789(height=280, y_offset=20, backlight=backlight),
            buttons=[GPIOButton(pin=11)],
            mixer_card="wm8960soundcard",
            mixer_control="Speaker",
            volume=volume,
            **kwargs,
        )

    @property
    def button(self):
        return self.buttons[0]
