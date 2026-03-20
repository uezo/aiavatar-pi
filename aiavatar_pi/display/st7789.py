"""ST7789 SPI LCD driver (RGB565).

Supports various ST7789-based displays (240x240, 240x280, 240x320, etc.).
Requires: spidev, RPi.GPIO
"""

from __future__ import annotations

import time

import spidev
import RPi.GPIO as GPIO

from .base import DisplayDriver


class ST7789(DisplayDriver):
    def __init__(
        self,
        *,
        width: int = 240,
        height: int = 240,
        dc_pin: int = 13,
        rst_pin: int = 7,
        led_pin: int = 15,
        spi_bus: int = 0,
        spi_device: int = 0,
        spi_speed_hz: int = 100_000_000,
        y_offset: int = 0,
        x_offset: int = 0,
        backlight: int = 50,
        backlight_active_low: bool = True,
    ):
        self._width = width
        self._height = height
        self._dc_pin = dc_pin
        self._rst_pin = rst_pin
        self._led_pin = led_pin
        self._y_offset = y_offset
        self._x_offset = x_offset
        self._backlight_active_low = backlight_active_low

        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup([dc_pin, rst_pin, led_pin], GPIO.OUT)
        GPIO.output(led_pin, GPIO.LOW)

        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = spi_speed_hz
        self.spi.mode = 0b00

        self._reset()
        self._init_display()
        self.fill_screen(0)
        self.set_backlight(backlight)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def _reset(self):
        GPIO.output(self._rst_pin, 1)
        time.sleep(0.1)
        GPIO.output(self._rst_pin, 0)
        time.sleep(0.1)
        GPIO.output(self._rst_pin, 1)
        time.sleep(0.12)

    def _send_command(self, cmd, *args):
        GPIO.output(self._dc_pin, 0)
        self.spi.xfer2([cmd])
        if args:
            GPIO.output(self._dc_pin, 1)
            self._send_data(list(args))

    def _send_data(self, data):
        GPIO.output(self._dc_pin, 1)
        try:
            self.spi.writebytes2(data)
        except AttributeError:
            if not isinstance(data, list):
                data = list(data)
            for i in range(0, len(data), 4096):
                self.spi.writebytes(data[i:i + 4096])

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

    def _set_window(self, x0, y0, x1, y1):
        x0 += self._x_offset
        x1 += self._x_offset
        y0 += self._y_offset
        y1 += self._y_offset
        self._send_command(0x2A, x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)
        self._send_command(0x2B, y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)
        self._send_command(0x2C)

    def draw_image(self, x, y, width, height, pixel_data):
        self._set_window(x, y, x + width - 1, y + height - 1)
        self._send_data(pixel_data)

    def fill_screen(self, color):
        self._set_window(0, 0, self._width - 1, self._height - 1)
        high = (color >> 8) & 0xFF
        low = color & 0xFF
        buf = [high, low] * (self._width * self._height)
        self._send_data(buf)

    def set_backlight(self, brightness):
        if self._backlight_active_low:
            GPIO.output(self._led_pin, GPIO.LOW if brightness > 0 else GPIO.HIGH)
        else:
            GPIO.output(self._led_pin, GPIO.HIGH if brightness > 0 else GPIO.LOW)

    def cleanup(self):
        self.spi.close()
        GPIO.cleanup()
