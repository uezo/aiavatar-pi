"""Display-agnostic image client for static face/mouth rendering.

Manages face switching, blink, lip sync, and glow state.
Subclasses implement _render() for their specific display output.
"""

import logging
import random
import threading
import time

from .base import AIAvatarClientBase

logger = logging.getLogger(__name__)
from .lipsync import LipSyncEngine


class AIAvatarImageClient(AIAvatarClientBase):

    def __init__(
        self,
        *,
        lipsync_config: dict = None,
        glow_config: dict = None,
        **kwargs,
    ):
        # Face/mouth state
        self._current_face = "neutral"
        self._last_mouth_shape = "closed"
        self._blink_active = False
        self._face_timer = None
        self._stop_event = threading.Event()

        # Lip sync
        self._lipsync = LipSyncEngine(**(lipsync_config or {}))

        # Glow state
        self._glow_intensity = 0.0
        self._glow_timer = None
        gc = glow_config or {}
        self._glow_solid = gc.get("solid", 3)
        self._glow_corner_radius = gc.get("corner_radius", 30)
        self._glow_opacity = gc.get("opacity", 1.0)
        self._glow_color_a = gc.get("color_a", [150, 50, 255])
        self._glow_color_b = gc.get("color_b", [255, 40, 180])

        # Init base
        super().__init__(**kwargs)

        # Wire callbacks
        self.on_face_updated = self._handle_face_updated
        self.on_playback_analyze = self._handle_playback_analyze
        self.on_playback_end = self._handle_playback_end
        self.on_voiced = self._handle_voiced

        # Background threads
        threading.Thread(target=self._prefetch_mouths, daemon=True).start()
        self._blink_thread = threading.Thread(target=self._blink_loop, daemon=True)
        self._blink_thread.start()

        # Initial render
        self._render()

    # ------------------------------------------------------------------
    # Abstract method
    # ------------------------------------------------------------------
    def _render(self):
        """Render the current visual state to the display.

        Subclass reads:
          self._current_face  - current face name (str)
          self._last_mouth_shape - current mouth shape (str)
          self._blink_active  - whether eyes-closed should show (bool)
          self._glow_intensity - glow strength 0.0..1.0 (float)

        The subclass is responsible for compositing, format conversion,
        and display output.
        """
        pass

    # ------------------------------------------------------------------
    # Face update handler
    # ------------------------------------------------------------------
    def _handle_face_updated(self, face_name, face_duration):
        if self._face_timer:
            self._face_timer.cancel()

        self._current_face = face_name.lower()
        self._render()

        if face_duration > 0 and face_name != "neutral":
            self._face_timer = threading.Timer(
                face_duration, self._handle_face_updated, args=("neutral", 0))
            self._face_timer.daemon = True
            self._face_timer.start()

    # ------------------------------------------------------------------
    # Lip sync handlers
    # ------------------------------------------------------------------
    def _handle_playback_analyze(self, rms, centroid01, t_sec):
        mouth_shape = self._lipsync.update(rms, centroid01, t_sec)
        if mouth_shape != self._last_mouth_shape:
            self._last_mouth_shape = mouth_shape
            if not self._blink_active:
                self._render()

    def _handle_playback_end(self):
        self._lipsync.reset()
        self._last_mouth_shape = "closed"
        self._render()

    # ------------------------------------------------------------------
    # Prefetch
    # ------------------------------------------------------------------
    def _prefetch_mouths(self):
        for mouth in ["half", "open", "e", "u"]:
            self._get_mouth_pil(mouth)
        logger.info("Mouth overlays loaded.")

    # ------------------------------------------------------------------
    # Blink
    # ------------------------------------------------------------------
    def _blink_loop(self):
        self._get_face_pil("eyes_closed")
        logger.info("Blink ready.")

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=random.uniform(3.0, 6.0))
            if self._stop_event.is_set():
                break

            if self._is_playing or self._current_face != "neutral":
                continue

            self._blink_active = True
            self._render()
            self._stop_event.wait(timeout=0.15)

            self._blink_active = False
            if self._current_face == "neutral" and not self._is_playing:
                self._render()

    # ------------------------------------------------------------------
    # Voiced indicator (glow state)
    # ------------------------------------------------------------------
    def _handle_voiced(self):
        was_off = self._glow_intensity == 0
        self._glow_intensity = 1.0
        if was_off:
            self._render()
        if self._glow_timer:
            self._glow_timer.cancel()
        self._glow_timer = threading.Timer(0.3, self._glow_off)
        self._glow_timer.daemon = True
        self._glow_timer.start()

    def _glow_off(self):
        self._glow_intensity = 0.0
        self._render()

    # ------------------------------------------------------------------
    # Mute (trigger re-render to show/hide indicator)
    # ------------------------------------------------------------------
    def mute(self):
        super().mute()
        self._render()

    def unmute(self):
        super().unmute()
        self._render()

    def toggle_mute(self) -> bool:
        result = super().toggle_mute()
        self._render()
        return result

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        self._stop_event.set()
        if self._face_timer:
            self._face_timer.cancel()
        if self._glow_timer:
            self._glow_timer.cancel()
        if self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1)
