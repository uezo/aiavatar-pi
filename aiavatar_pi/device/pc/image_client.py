"""PC image client using pygame window and PyAudio.

Inherits AIAvatarImageClient for face/mouth/blink/glow state management.
Implements _render() for pygame window display.

Requires: pygame, Pillow, numpy, PyAudio
"""

import asyncio
import logging
import threading

import numpy as np
import pygame
from PIL import Image

from ...audio.pyaudio import PyAudioBackend
from ...image_client import AIAvatarImageClient

logger = logging.getLogger(__name__)


class PCImageClient(AIAvatarImageClient):

    def __init__(
        self,
        *,
        display_width: int = 480,
        display_height: int = 480,
        window_title: str = "AIAvatar",
        **kwargs,
    ):
        self._display_width = display_width
        self._display_height = display_height

        # --- pygame (display only, avoid SDL audio conflicting with PyAudio) ---
        pygame.display.init()
        self._screen = pygame.display.set_mode((display_width, display_height))
        pygame.display.set_caption(window_title)

        # --- Frame buffer (written by worker threads, read by main thread) ---
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._running = False

        # --- Image caches ---
        self._composite_cache = {}

        # --- Glow mask ---
        self._glow_alpha_mask = None
        self._glow_color_map = None

        # Init parent chain (AIAvatarImageClient → AIAvatarClientBase)
        super().__init__(**kwargs)

        # Audio backend
        if not self.audio_backend:
            self.audio_backend = PyAudioBackend()

        # Build glow mask and mute indicator
        self._build_glow_mask()
        self._build_mute_indicator(display_width, display_height)

    # ------------------------------------------------------------------
    # run(): call this instead of asyncio.run(client.start())
    # ------------------------------------------------------------------
    def run(self):
        """Start WebSocket in background thread, run pygame loop on main thread."""
        self._running = True
        ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        ws_thread.start()

        clock = pygame.time.Clock()
        try:
            while self._running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._running = False
                        break

                with self._frame_lock:
                    frame = self._latest_frame
                    self._latest_frame = None

                if frame is not None:
                    surface = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
                    self._screen.blit(surface, (0, 0))
                    pygame.display.flip()

                clock.tick(60)
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def _run_ws(self):
        try:
            asyncio.run(self.start())
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self._running = False

    # ------------------------------------------------------------------
    # _render() implementation
    # ------------------------------------------------------------------
    def _render(self):
        if self._blink_active:
            img = self._get_display_image("eyes_closed", "closed")
        else:
            img = self._get_display_image(self._current_face, self._last_mouth_shape)

        if img is None:
            return

        frame = np.array(img.convert("RGB"))

        if self._glow_intensity > 0 and self._glow_alpha_mask is not None:
            a = self._glow_alpha_mask * self._glow_intensity
            frame = (frame * (1.0 - a) + self._glow_color_map * a).astype(np.uint8)

        self._overlay_mute_indicator(frame)

        with self._frame_lock:
            self._latest_frame = frame

    # ------------------------------------------------------------------
    # Image compositing
    # ------------------------------------------------------------------
    def _get_display_image(self, face_name, mouth_name):
        key = (face_name, mouth_name)
        if key not in self._composite_cache:
            face_img = self._get_face_pil(face_name)
            if face_img is None:
                return None
            face_resized = self._crop_to_cover(face_img)
            if mouth_name != "closed":
                mouth_img = self._get_mouth_pil(mouth_name)
                if mouth_img:
                    mouth_resized = self._crop_to_cover(mouth_img)
                    face_resized = Image.alpha_composite(face_resized, mouth_resized)
            self._composite_cache[key] = face_resized
        return self._composite_cache[key]

    def _crop_to_cover(self, img):
        w, h = self._display_width, self._display_height
        orig_w, orig_h = img.size
        scale = max(w / orig_w, h / orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        img = img.resize((new_w, new_h))
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        return img.crop((left, top, left + w, top + h)).convert("RGBA")

    # ------------------------------------------------------------------
    # Glow mask
    # ------------------------------------------------------------------
    def _build_glow_mask(self):
        w, h = self._display_width, self._display_height
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
        self._glow_color_map = (color_a * (1 - t) + color_b * t).astype(np.float32)
        self._glow_alpha_mask = (alpha[:, :, np.newaxis] * self._glow_opacity).astype(np.float32)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        super().cleanup()
        pygame.quit()
