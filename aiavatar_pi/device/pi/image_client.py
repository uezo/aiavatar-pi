"""Raspberry Pi image client using SPI LCD, ALSA audio, and optional GPIO buttons.

Inherits AIAvatarImageClient for face/mouth/blink/glow state management.
Implements _render() for SPI LCD display output.

Requires: alsa-utils, Pillow, numpy, spidev, RPi.GPIO
"""

import threading

import numpy as np
from PIL import Image

from ...audio.alsa import ALSABackend
from ...display.st7789 import ST7789
from ...image_client import AIAvatarImageClient


class PiImageClient(AIAvatarImageClient):

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

        # --- Display pixel caches ---
        self._composite_cache = {}
        self._face_only_cache = {}

        # --- Glow mask arrays (built after super().__init__) ---
        self._glow_alpha = None
        self._glow_color = None

        # Init parent chain (AIAvatarImageClient → AIAvatarClientBase)
        super().__init__(**kwargs)

        # Audio backend (ALSA)
        if not self.audio_backend:
            self.audio_backend = ALSABackend(
                input_device=input_device,
                output_device=output_device,
                mixer_card=mixer_card,
                mixer_control=mixer_control,
            )

        # Build glow mask and mute indicator for LCD resolution
        self._build_glow_mask()
        self._build_mute_indicator()

        # Set hardware volume
        self.audio_backend.set_volume(volume)

    # ------------------------------------------------------------------
    # _render() implementation
    # ------------------------------------------------------------------
    def _render(self):
        if self._blink_active:
            data = self._get_face_pixels("eyes_closed")
        else:
            data = self._get_composite(self._current_face, self._last_mouth_shape)

        if data is None:
            return

        if self._glow_intensity > 0 and self._glow_alpha is not None:
            data = self._apply_glow(data)

        if self._user_muted and self._mute_offsets:
            data = self._overlay_mute(data)

        with self._lcd_lock:
            self.lcd.draw_image(0, 0, self.lcd.width, self.lcd.height, data)

    # ------------------------------------------------------------------
    # Pixel data cache
    # ------------------------------------------------------------------
    def _get_face_pixels(self, face_name):
        if face_name not in self._face_only_cache:
            face_img = self._get_face_pil(face_name)
            if face_img is None:
                return None
            self._face_only_cache[face_name] = self.lcd.image_to_pixel_data(
                self.lcd.crop_to_cover(face_img))
        return self._face_only_cache[face_name]

    def _get_composite(self, face_name, mouth_name):
        if mouth_name == "closed":
            return self._get_face_pixels(face_name)
        key = (face_name, mouth_name)
        if key not in self._composite_cache:
            face_img = self._get_face_pil(face_name)
            if face_img is None:
                return None
            mouth_img = self._get_mouth_pil(mouth_name)
            if mouth_img is None:
                return self._get_face_pixels(face_name)
            composite = Image.alpha_composite(
                self.lcd.crop_to_cover(face_img),
                self.lcd.crop_to_cover(mouth_img))
            self._composite_cache[key] = self.lcd.image_to_pixel_data(composite)
        return self._composite_cache[key]

    # ------------------------------------------------------------------
    # Mute indicator
    # ------------------------------------------------------------------
    def _build_mute_indicator(self):
        w, h = self.lcd.width, self.lcd.height
        bpp = self.lcd.bytes_per_pixel
        radius = max(4, min(w, h) // 30)
        margin = radius + 6
        cx, cy = w - margin, margin

        # Pre-compute byte offsets for circle pixels
        self._mute_offsets = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    px, py = cx + dx, cy + dy
                    if 0 <= px < w and 0 <= py < h:
                        self._mute_offsets.append((py * w + px) * bpp)

        # (220, 50, 50) in native pixel format
        self._mute_color_bytes = self.lcd.encode_color(220, 50, 50)

    def _overlay_mute(self, data):
        buf = bytearray(data)
        color = self._mute_color_bytes
        bpp = len(color)
        for offset in self._mute_offsets:
            buf[offset:offset + bpp] = color
        return bytes(buf)

    # ------------------------------------------------------------------
    # Glow (LCD-resolution-specific)
    # ------------------------------------------------------------------
    def _build_glow_mask(self):
        w, h = self.lcd.width, self.lcd.height
        solid = self._glow_solid
        R = self._glow_corner_radius

        y = np.arange(h, dtype=np.float32).reshape(-1, 1)
        x = np.arange(w, dtype=np.float32).reshape(1, -1)

        dx = np.minimum(x, w - 1 - x)
        dy = np.minimum(y, h - 1 - y)
        in_corner = (dx < R) & (dy < R)
        corner_dist = R - np.sqrt((R - dx) ** 2 + (R - dy) ** 2)
        rect_dist = np.minimum(dx, dy)
        dist = np.where(in_corner, np.maximum(0, corner_dist), rect_dist)

        alpha = np.clip(solid + 1 - dist, 0, 1).astype(np.float32)

        t = (((w - 1 - x) / (w - 1) + y / (h - 1)) / 2.0)[:, :, np.newaxis]
        color_a = np.array(self._glow_color_a, dtype=np.float32)
        color_b = np.array(self._glow_color_b, dtype=np.float32)
        self._glow_color = (color_a * (1 - t) + color_b * t).astype(np.float32)
        self._glow_alpha = (alpha[:, :, np.newaxis] * self._glow_opacity).astype(np.float32)

    def _apply_glow(self, pixel_data):
        w, h = self.lcd.width, self.lcd.height

        frame = self.lcd.pixel_data_to_rgb_array(pixel_data, w, h)

        a = self._glow_alpha * self._glow_intensity
        frame = (frame * (1.0 - a) + self._glow_color * a).astype(np.uint8)

        return self.lcd.rgb_array_to_pixel_data(frame)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        super().cleanup()
        for btn in self.buttons:
            btn.cleanup()
        self.lcd.cleanup()
