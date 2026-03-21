"""Raspberry Pi motion client using SPI LCD, ALSA audio, and optional GPIO buttons.

Inherits AIAvatarMotionClient for video loop, mouth compositing, and glow.
Implements _display_frame() for SPI LCD display output.

Requires: alsa-utils, ffmpeg, Pillow, numpy, spidev, RPi.GPIO
"""

import threading

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
        pixel_data = self.lcd.rgb_array_to_pixel_data(rgb_frame)
        with self._lcd_lock:
            self.lcd.draw_image(0, 0, width, height, pixel_data)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        super().cleanup()
        for btn in self.buttons:
            btn.cleanup()
        self.lcd.cleanup()
