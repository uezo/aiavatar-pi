"""PC motion client using pygame window and PyAudio.

Inherits AIAvatarMotionClient for video loop, mouth compositing, and glow.
Implements _display_frame() for pygame window display.

Requires: pygame, ffmpeg, Pillow, numpy, PyAudio
"""

import asyncio
import logging
import threading

import pygame

from ...audio.pyaudio import PyAudioBackend
from ...motion_client import AIAvatarMotionClient

logger = logging.getLogger(__name__)


class PCMotionClient(AIAvatarMotionClient):

    def __init__(
        self,
        *,
        display_width: int = 480,
        display_height: int = 480,
        window_title: str = "AIAvatar",
        **kwargs,
    ):
        # --- pygame (display only, avoid SDL audio conflicting with PyAudio) ---
        pygame.display.init()
        self._screen = pygame.display.set_mode((display_width, display_height))
        pygame.display.set_caption(window_title)

        # --- Frame buffer (written by video thread, read by main thread) ---
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._running = False

        # Init parent chain (AIAvatarMotionClient → AIAvatarClientBase)
        super().__init__(
            display_width=display_width,
            display_height=display_height,
            **kwargs,
        )

        # Audio backend
        if not self.audio_backend:
            self.audio_backend = PyAudioBackend()

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
    # _display_frame() implementation
    # ------------------------------------------------------------------
    def _display_frame(self, rgb_frame, width, height):
        with self._frame_lock:
            self._latest_frame = rgb_frame.copy()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        super().cleanup()
        pygame.quit()
