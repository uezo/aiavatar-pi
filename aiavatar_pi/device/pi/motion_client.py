"""Raspberry Pi motion client using SPI LCD, ALSA audio, and optional GPIO buttons.

Inherits AIAvatarMotionClient for video loop, mouth compositing, and glow.
Implements _display_frame() for SPI LCD RGB565 display output.

Requires: alsa-utils, ffmpeg, Pillow, numpy, spidev, RPi.GPIO
"""

import threading

import numpy as np

from ...audio.alsa import ALSABackend
from ...display.st7789 import ST7789
from ...motion_client import AIAvatarMotionClient


class PiMotionClient(AIAvatarMotionClient):

    def __init__(
        self,
        *,
        lcd=None,
        buttons=None,
        input_device: str = None,
        output_device: str = None,
        mixer_card: str = None,
        mixer_control: str = None,
        volume: int = 100,
        **kwargs,
    ):
        # --- LCD ---
        self.lcd = lcd or ST7789()
        self._lcd_lock = threading.Lock()

        # --- Buttons (optional) ---
        self.buttons = list(buttons) if buttons else []

        # Init parent chain (AIAvatarMotionClient → AIAvatarClientBase)
        super().__init__(
            display_width=self.lcd.width,
            display_height=self.lcd.height,
            **kwargs,
        )

        # Audio backend (ALSA)
        if not self.audio_backend:
            self.audio_backend = ALSABackend(
                input_device=input_device,
                output_device=output_device,
                mixer_card=mixer_card,
                mixer_control=mixer_control,
            )

        # Set hardware volume
        self.audio_backend.set_volume(volume)

    # ------------------------------------------------------------------
    # _display_frame() implementation
    # ------------------------------------------------------------------
    def _display_frame(self, rgb_frame, width, height):
        rgb565_data = self._rgb_to_rgb565(rgb_frame)
        with self._lcd_lock:
            self.lcd.draw_image(0, 0, width, height, rgb565_data)

    @staticmethod
    def _rgb_to_rgb565(frame):
        """Convert numpy RGB (h,w,3) to RGB565 big-endian bytes."""
        r = frame[:, :, 0].astype(np.uint16)
        g = frame[:, :, 1].astype(np.uint16)
        b = frame[:, :, 2].astype(np.uint16)
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return rgb565.astype(">u2").tobytes()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        super().cleanup()
        for btn in self.buttons:
            btn.cleanup()
        self.lcd.cleanup()
