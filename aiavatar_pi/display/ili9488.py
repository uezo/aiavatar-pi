"""ILI9488 SPI LCD driver (RGB666).

Supports ILI9488-based displays (typically 480x320).
SPI mode requires RGB666 (18-bit, 3 bytes per pixel).
Requires: spidev, RPi.GPIO
"""

from __future__ import annotations

import time

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from .spi_display import SPIDisplay


class ILI9488(SPIDisplay):
    def __init__(
        self,
        *,
        width: int = 320,
        height: int = 480,
        spi_speed_hz: int = 24_000_000,
        **kwargs,
    ):
        super().__init__(
            width=width,
            height=height,
            spi_speed_hz=spi_speed_hz,
            **kwargs,
        )

    # -- Pixel format: RGB666 (3 bytes per pixel) --

    @property
    def bytes_per_pixel(self) -> int:
        return 3

    def image_to_pixel_data(self, img) -> bytes:
        """Convert PIL RGB image to RGB666 bytes."""
        img = img.convert("RGB")
        if _HAS_NUMPY:
            arr = np.array(img, dtype=np.uint8)
            return (arr & 0xFC).tobytes()
        else:
            raw = img.tobytes()
            return bytes(b & 0xFC for b in raw)

    def rgb_array_to_pixel_data(self, frame) -> bytes:
        """Convert numpy RGB (h,w,3) uint8 array to RGB666 bytes."""
        return (frame.astype(np.uint8) & 0xFC).tobytes()

    def pixel_data_to_rgb_array(self, data, w: int, h: int):
        """Convert RGB666 bytes to numpy RGB (h,w,3) float32 array."""
        arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
        return arr.astype(np.float32)

    def encode_color(self, r: int, g: int, b: int) -> tuple:
        """Encode single RGB color as RGB666 byte values."""
        return (r & 0xFC, g & 0xFC, b & 0xFC)

    # -- ILI9488 initialization --

    def _init_display(self):
        self._send_command(0x11)          # Sleep out
        time.sleep(0.12)
        self._send_command(0xE0,          # Positive gamma control
                           0x00, 0x07, 0x10, 0x09, 0x17,
                           0x0B, 0x41, 0x89, 0x4B, 0x0A,
                           0x0C, 0x0E, 0x18, 0x1B, 0x0F)
        self._send_command(0xE1,          # Negative gamma control
                           0x00, 0x17, 0x1A, 0x04, 0x0E,
                           0x06, 0x2F, 0x45, 0x43, 0x02,
                           0x0A, 0x09, 0x32, 0x36, 0x0F)
        self._send_command(0xC0, 0x17, 0x15)          # Power control 1
        self._send_command(0xC1, 0x41)                 # Power control 2
        self._send_command(0xC5, 0x00, 0x12, 0x80)     # VCOM control
        self._send_command(0x36, 0x48)                 # Memory access control
        self._send_command(0x3A, 0x66)                 # Interface pixel format (RGB666)
        self._send_command(0xB0, 0x00)                 # Interface mode control
        self._send_command(0xB1, 0xA0)                 # Frame rate control
        self._send_command(0xB4, 0x02)                 # Display inversion control
        self._send_command(0xB6, 0x02, 0x02)           # Display function control
        self._send_command(0xE9, 0x00)                 # Set image function
        self._send_command(0xF7, 0xA9, 0x51, 0x2C, 0x82)  # Adjust control 3
        self._send_command(0x20)          # Display inversion off
        self._send_command(0x29)          # Display on
