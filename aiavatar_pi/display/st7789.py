"""ST7789 SPI LCD driver (RGB565).

Supports various ST7789-based displays (240x240, 240x280, 240x320, etc.).
Requires: spidev, RPi.GPIO
"""

from __future__ import annotations

import time

from .spi_display import SPIDisplay


class ST7789(SPIDisplay):
    def __init__(self, *, spi_speed_hz: int = 100_000_000, **kwargs):
        super().__init__(spi_speed_hz=spi_speed_hz, **kwargs)

    def _init_display(self):
        self._send_command(0x11)          # Sleep out
        time.sleep(0.12)
        self._send_command(0x36, 0xC0)    # Memory data access control
        self._send_command(0x3A, 0x05)    # Interface pixel format (RGB565)
        self._send_command(0xB2, 0x0C, 0x0C, 0x00, 0x33, 0x33)  # Porch control
        self._send_command(0xB7, 0x35)    # Gate control
        self._send_command(0xBB, 0x32)    # VCOM setting
        self._send_command(0xC2, 0x01)    # VDV/VRH command enable
        self._send_command(0xC3, 0x15)    # VRH set
        self._send_command(0xC4, 0x20)    # VDV set
        self._send_command(0xC6, 0x0F)    # Frame rate control
        self._send_command(0xD0, 0xA4, 0xA1)  # Power control
        self._send_command(0xE0, 0xD0, 0x08, 0x0E, 0x09, 0x09, 0x05, 0x31,
                           0x33, 0x48, 0x17, 0x14, 0x15, 0x31, 0x34)  # Positive gamma
        self._send_command(0xE1, 0xD0, 0x08, 0x0E, 0x09, 0x09, 0x15, 0x31,
                           0x33, 0x48, 0x17, 0x14, 0x15, 0x31, 0x34)  # Negative gamma
        self._send_command(0x21)          # Display inversion on
        self._send_command(0x29)          # Display on
