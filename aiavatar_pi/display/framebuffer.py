"""Linux framebuffer display driver (RGB565 little-endian).

Writes pixel data to a Linux framebuffer device (e.g. /dev/fb1).
The kernel fbtft driver handles SPI transfer with DMA, giving much
better performance than userspace spidev for large displays.

Requires: fbtft kernel driver configured for the target display.
"""

from __future__ import annotations

import mmap
import os

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from .base import DisplayDriver


class FramebufferDisplay(DisplayDriver):
    def __init__(
        self,
        *,
        fb_device: str = "/dev/fb1",
        width: int = 480,
        height: int = 320,
    ):
        self._width = width
        self._height = height
        self._bpp = 2  # RGB565: 2 bytes per pixel
        self._line_length = self._width * self._bpp

        self._fb_fd = os.open(fb_device, os.O_RDWR)
        fb_size = self._width * self._height * self._bpp
        self._fb = mmap.mmap(self._fb_fd, fb_size)

        self.fill_screen(0)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    # -- Pixel format: RGB565 little-endian (Linux framebuffer native) --

    def image_to_pixel_data(self, img) -> bytes:
        """Convert PIL RGB image to RGB565 little-endian bytes."""
        img = img.convert("RGB")
        if _HAS_NUMPY:
            arr = np.array(img)
            r = arr[:, :, 0].astype(np.uint16)
            g = arr[:, :, 1].astype(np.uint16)
            b = arr[:, :, 2].astype(np.uint16)
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            return rgb565.astype("<u2").tobytes()
        else:
            w, h = img.size
            raw = img.tobytes()
            pixel_data = bytearray(w * h * 2)
            for i in range(w * h):
                r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pixel_data[i * 2] = rgb565 & 0xFF
                pixel_data[i * 2 + 1] = (rgb565 >> 8) & 0xFF
            return bytes(pixel_data)

    def rgb_array_to_pixel_data(self, frame) -> bytes:
        """Convert numpy RGB (h,w,3) uint8 array to RGB565 little-endian bytes."""
        r = frame[:, :, 0].astype(np.uint16)
        g = frame[:, :, 1].astype(np.uint16)
        b = frame[:, :, 2].astype(np.uint16)
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return rgb565.astype("<u2").tobytes()

    def pixel_data_to_rgb_array(self, data, w: int, h: int):
        """Convert RGB565 little-endian bytes to numpy RGB (h,w,3) float32 array."""
        raw = np.frombuffer(data, dtype="<u2").reshape(h, w)
        r = ((raw >> 11) & 0x1F).astype(np.float32) * (255.0 / 31)
        g = ((raw >> 5) & 0x3F).astype(np.float32) * (255.0 / 63)
        b = (raw & 0x1F).astype(np.float32) * (255.0 / 31)
        return np.stack([r, g, b], axis=2)

    def encode_color(self, r: int, g: int, b: int) -> tuple:
        """Encode single RGB color as RGB565 little-endian byte values."""
        r5 = r >> 3
        g6 = g >> 2
        b5 = b >> 3
        val = (r5 << 11) | (g6 << 5) | b5
        return (val & 0xFF, (val >> 8) & 0xFF)

    # -- Drawing --

    def draw_image(self, x, y, width, height, pixel_data):
        if x == 0 and width == self._width:
            offset = y * self._line_length
            self._fb.seek(offset)
            self._fb.write(pixel_data)
        else:
            row_bytes = width * self._bpp
            for row in range(height):
                offset = ((y + row) * self._width + x) * self._bpp
                start = row * row_bytes
                self._fb.seek(offset)
                self._fb.write(pixel_data[start:start + row_bytes])

    def fill_screen(self, color):
        low = color & 0xFF
        high = (color >> 8) & 0xFF
        buf = bytes([low, high]) * (self._width * self._height)
        self._fb.seek(0)
        self._fb.write(buf)

    def cleanup(self):
        self._fb.close()
        os.close(self._fb_fd)
