"""Display-agnostic motion client for video loop with lip-synced mouth overlay.

Uses ffmpeg for video decoding, numpy/PIL for mouth sprite compositing.
Subclasses implement _display_frame() for their specific display output.

Requires: ffmpeg, Pillow, numpy
"""

import gc as gc_mod
import io
import json
import logging
import math
import subprocess
import threading
import time
import urllib.request

import numpy as np
from PIL import Image

from .base import AIAvatarClientBase
from .lipsync import LipSyncEngine

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _detect_device():
    """Detect Raspberry Pi model from device tree."""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return f.read().lower()
    except Exception:
        return "generic"


def _get_ffmpeg_cmd(video_path, width, height, pix_fmt="rgb24"):
    """Build ffmpeg command with device-specific optimizations."""
    model = _detect_device()
    input_args = []
    scale_flags = "neighbor"

    if "zero 2" in model or "raspberry pi 3" in model:
        input_args = ["-threads", "4"]
    elif "zero" in model:
        input_args = ["-vcodec", "h264_v4l2m2m"]
    elif "raspberry pi 4" in model or "raspberry pi 5" in model:
        input_args = ["-threads", "4"]
        scale_flags = "bicubic"

    return ["ffmpeg"] + input_args + [
        "-i", video_path,
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase:flags={scale_flags},crop={width}:{height}",
        "-vcodec", "rawvideo",
        "-pix_fmt", pix_fmt,
        "-f", "image2pipe",
        "-loglevel", "quiet",
        "-",
    ]


def _fetch_json(url):
    """Fetch JSON from URL."""
    resp = urllib.request.urlopen(url, timeout=10)
    return json.loads(resp.read())


def _fetch_image(url):
    """Fetch image from URL as RGBA PIL Image."""
    resp = urllib.request.urlopen(url, timeout=5)
    return Image.open(io.BytesIO(resp.read())).convert("RGBA")


# ------------------------------------------------------------------
# Motion Client
# ------------------------------------------------------------------

class AIAvatarMotionClient(AIAvatarClientBase):

    _GLOW_SOLID = 3
    _GLOW_CORNER_RADIUS = 30

    def __init__(
        self,
        *,
        display_width: int,
        display_height: int,
        lipsync_config: dict = None,
        glow_config: dict = None,
        **kwargs,
    ):
        character_url = kwargs.get("character_url", "").rstrip("/")
        self._character_url = character_url
        self._video_path = f"{character_url}/main.mp4"
        self._lipsync_config = lipsync_config or {}

        # Display dimensions
        self._display_width = display_width
        self._display_height = display_height

        # Video state
        self._video_proc = None
        self._video_thread = None
        self._stop_event = threading.Event()

        # Mouth overlay
        self._track_data = None
        self._scaled_quads = None
        self._mouth_sprites = {}
        self._mouth_shape = "closed"
        self._lipsync = None

        # Voiced indicator / glow
        self._voiced_until = 0.0
        self._glow_intensity = 0.0
        self._glow_alpha = None
        self._glow_color = None
        gc = glow_config or {}
        self._glow_solid = gc.get("solid", self._GLOW_SOLID)
        self._glow_corner_radius = gc.get("corner_radius", self._GLOW_CORNER_RADIUS)
        self._glow_opacity = gc.get("opacity", 1.0)
        self._glow_color_a = gc.get("color_a", [150, 50, 255])
        self._glow_color_b = gc.get("color_b", [255, 40, 180])

        # Load character assets
        if character_url:
            self._load_character(character_url)

        # Init base
        super().__init__(**kwargs)

        # Wire callbacks
        self.on_voiced = self._handle_voiced
        if self._scaled_quads and self._mouth_sprites:
            self._lipsync = LipSyncEngine(**self._lipsync_config)
            self.on_playback_analyze = self._handle_playback_analyze
            self.on_playback_end = self._handle_playback_end

        self._build_glow_mask()
        self._build_mute_indicator(display_width, display_height)

        # Start video loop
        self._video_thread = threading.Thread(target=self._video_loop, daemon=True)
        self._video_thread.start()

    # ------------------------------------------------------------------
    # Reconnection hook
    # ------------------------------------------------------------------
    def _on_ws_connected(self):
        if self._mouth_sprites:
            return

        character_url = self._character_url
        if not character_url:
            return

        logger.info("Retrying character asset loading...")
        self._load_character(character_url)

        if self._scaled_quads and self._mouth_sprites and self._lipsync is None:
            self._lipsync = LipSyncEngine(**self._lipsync_config)
            self.on_playback_analyze = self._handle_playback_analyze
            self.on_playback_end = self._handle_playback_end
            logger.info("Lip sync enabled after reconnection.")

    # ------------------------------------------------------------------
    # Abstract method
    # ------------------------------------------------------------------
    def _display_frame(self, rgb_frame, width, height):
        """Display a composited frame.

        Args:
            rgb_frame: numpy array (height, width, 3), dtype uint8, RGB.
            width: frame width in pixels.
            height: frame height in pixels.

        Subclass converts to display format and outputs.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Character asset loading
    # ------------------------------------------------------------------
    def _get_video_dimensions(self):
        """Get actual video dimensions using ffprobe."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "stream=width,height",
                 "-of", "csv=p=0", self._video_path],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                return int(parts[0]), int(parts[1])
        except Exception as e:
            logger.warning(f"ffprobe failed: {e}")
        return None, None

    def _load_character(self, base_url):
        try:
            self._track_data = _fetch_json(f"{base_url}/mouth_track.json")
            logger.info(f"Track loaded: {len(self._track_data['frames'])} frames @ {self._track_data['fps']}fps")
        except Exception as e:
            logger.warning(f"Failed to load track data: {e}")
            return

        self._video_width, self._video_height = self._get_video_dimensions()
        self._scaled_quads = self._precompute_quads()

        for name in ["closed", "open", "half", "e", "u"]:
            try:
                self._mouth_sprites[name] = _fetch_image(f"{base_url}/mouth/{name}.png")
            except Exception as e:
                if name in ("closed", "open"):
                    logger.warning(f"mouth/{name}.png not found: {e}")
        logger.info(f"Mouth sprites loaded: {list(self._mouth_sprites.keys())}")

    def _precompute_quads(self):
        """Scale quad coordinates from tracking space to display coordinates.

        Two-step mapping: tracking → video → display.
        If video dimensions match tracking dimensions, reduces to single step.
        """
        data = self._track_data
        track_w, track_h = data["width"], data["height"]
        disp_w, disp_h = self._display_width, self._display_height

        vid_w = getattr(self, "_video_width", None) or track_w
        vid_h = getattr(self, "_video_height", None) or track_h

        # Step 1: tracking space → video space (cover crop)
        s1 = max(vid_w / track_w, vid_h / track_h)
        cx1 = (track_w * s1 - vid_w) / 2
        cy1 = (track_h * s1 - vid_h) / 2

        # Step 2: video space → display space (same as ffmpeg cover crop)
        s2 = max(disp_w / vid_w, disp_h / vid_h)
        cx2 = (vid_w * s2 - disp_w) / 2
        cy2 = (vid_h * s2 - disp_h) / 2

        # Composed transform
        scale = s1 * s2
        crop_x = cx1 * s2 + cx2
        crop_y = cy1 * s2 + cy2

        calib = data.get("calibration", {"offset": [0, 0], "scale": 1, "rotation": 0})
        calib_applied = data.get("calibrationApplied", False)

        quads = []
        for frame in data["frames"]:
            if not frame.get("valid", False):
                quads.append(None)
                continue

            quad = frame["quad"]
            if calib_applied:
                quad = self._apply_calibration(quad, calib)

            quads.append([(x * scale - crop_x, y * scale - crop_y) for x, y in quad])

        return quads

    @staticmethod
    def _apply_calibration(quad, calib):
        """Apply calibration offset/scale/rotation to quad."""
        ox = calib.get("offset", [0, 0])[0]
        oy = calib.get("offset", [0, 0])[1]
        s = calib.get("scale", 1)
        r = math.radians(calib.get("rotation", 0))

        cx = sum(p[0] for p in quad) / 4
        cy = sum(p[1] for p in quad) / 4
        cos_r, sin_r = math.cos(r), math.sin(r)

        return [
            (
                (p[0] - cx) * s * cos_r - (p[1] - cy) * s * sin_r + cx + ox,
                (p[0] - cx) * s * sin_r + (p[1] - cy) * s * cos_r + cy + oy,
            )
            for p in quad
        ]

    # ------------------------------------------------------------------
    # Video loop
    # ------------------------------------------------------------------
    def _start_ffmpeg(self):
        w, h = self._display_width, self._display_height
        cmd = _get_ffmpeg_cmd(self._video_path, w, h, "rgb24")
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=w * h * 3)

    def _video_loop(self):
        w, h = self._display_width, self._display_height
        frame_size = w * h * 3

        fps = self._track_data["fps"] if self._track_data else 24.0
        spf = 1.0 / fps

        buffer = bytearray(frame_size)
        frame_index = 0
        total_frames = len(self._scaled_quads) if self._scaled_quads else 0

        gc_mod.collect()
        gc_mod.disable()

        fail_count = 0
        self._video_proc = self._start_ffmpeg()
        proc_start = time.monotonic()

        try:
            next_frame_time = time.monotonic()
            while not self._stop_event.is_set():
                read = self._video_proc.stdout.readinto(buffer)
                if read != frame_size:
                    # EOF or error → restart ffmpeg to loop
                    try:
                        self._video_proc.kill()
                        self._video_proc.wait(timeout=1)
                    except Exception:
                        pass

                    # Backoff on rapid failures
                    if time.monotonic() - proc_start < 1.0:
                        fail_count += 1
                        delay = min(0.5 * (2 ** (fail_count - 1)), 5.0)
                        logger.warning(
                            "ffmpeg exited quickly (attempt %d), retrying in %.1fs",
                            fail_count, delay)
                        if self._stop_event.wait(timeout=delay):
                            break
                    else:
                        fail_count = 0

                    self._video_proc = self._start_ffmpeg()
                    proc_start = time.monotonic()
                    frame_index = 0
                    next_frame_time = time.monotonic()
                    continue

                # Re-check each frame (assets may be loaded after reconnection)
                if self._scaled_quads and self._mouth_sprites:
                    if total_frames == 0:
                        total_frames = len(self._scaled_quads)
                        fps = self._track_data["fps"]
                        spf = 1.0 / fps
                        frame_index = 0
                    frame = self._composite_frame(buffer, w, h, frame_index)
                    frame_index = (frame_index + 1) % total_frames
                else:
                    frame = np.frombuffer(buffer, dtype=np.uint8).reshape(h, w, 3).copy()
                    self._draw_voiced_indicator(frame)

                self._overlay_mute_indicator(frame)
                self._display_frame(frame, w, h)

                # Pace to target FPS
                next_frame_time += spf
                sleep = next_frame_time - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
        finally:
            gc_mod.enable()
            if self._video_proc:
                try:
                    self._video_proc.kill()
                    self._video_proc.wait(timeout=1)
                except Exception:
                    pass
                self._video_proc = None

    # ------------------------------------------------------------------
    # Frame compositing
    # ------------------------------------------------------------------
    def _composite_frame(self, rgb_buffer, w, h, frame_index):
        """Overlay mouth sprite on RGB frame, return numpy RGB array."""
        frame = np.frombuffer(rgb_buffer, dtype=np.uint8).reshape(h, w, 3).copy()

        quad = self._scaled_quads[frame_index]
        if quad is not None:
            sprite = self._mouth_sprites.get(self._mouth_shape)
            if sprite is None:
                sprite = self._mouth_sprites.get("closed")

            if sprite is not None:
                tl, tr, br, bl = quad
                cx = (tl[0] + tr[0] + br[0] + bl[0]) / 4
                cy = (tl[1] + tr[1] + br[1] + bl[1]) / 4
                mw = (math.hypot(tr[0] - tl[0], tr[1] - tl[1]) +
                      math.hypot(br[0] - bl[0], br[1] - bl[1])) / 2
                mh = (math.hypot(bl[0] - tl[0], bl[1] - tl[1]) +
                      math.hypot(br[0] - tr[0], br[1] - tr[1])) / 2
                angle = math.degrees(math.atan2(tr[1] - tl[1], tr[0] - tl[0]))

                if mw >= 1 and mh >= 1:
                    resized = sprite.resize(
                        (max(1, round(mw)), max(1, round(mh))), Image.LANCZOS)
                    if abs(angle) > 0.5:
                        resized = resized.rotate(
                            -angle, expand=True, resample=Image.BILINEAR)

                    pw, ph = resized.size
                    px = round(cx - pw / 2)
                    py = round(cy - ph / 2)
                    sx, sy = max(0, -px), max(0, -py)
                    ex, ey = min(pw, w - px), min(ph, h - py)

                    if sx < ex and sy < ey:
                        sprite_arr = np.array(resized)
                        rgb = sprite_arr[sy:ey, sx:ex, :3]
                        alpha = sprite_arr[sy:ey, sx:ex, 3:4].astype(np.float32) / 255.0
                        fy0, fy1 = py + sy, py + ey
                        fx0, fx1 = px + sx, px + ex
                        frame[fy0:fy1, fx0:fx1] = (
                            rgb * alpha + frame[fy0:fy1, fx0:fx1] * (1.0 - alpha)
                        ).astype(np.uint8)

        self._draw_voiced_indicator(frame)
        return frame

    # ------------------------------------------------------------------
    # Voiced indicator (glow)
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
        self._glow_color = (color_a * (1 - t) + color_b * t).astype(np.float32)
        self._glow_alpha = (alpha[:, :, np.newaxis] * self._glow_opacity).astype(np.float32)

    def _handle_voiced(self):
        self._voiced_until = time.monotonic() + 0.1

    def _draw_voiced_indicator(self, frame):
        now = time.monotonic()
        if now < self._voiced_until:
            self._glow_intensity = 1.0
        else:
            self._glow_intensity *= 0.75

        if self._glow_intensity < 0.01:
            self._glow_intensity = 0.0
            return

        a = self._glow_alpha * self._glow_intensity
        frame[:] = (frame * (1.0 - a) + self._glow_color * a).astype(np.uint8)

    # ------------------------------------------------------------------
    # Lip sync
    # ------------------------------------------------------------------
    def _handle_playback_analyze(self, rms, centroid01, t_sec):
        self._mouth_shape = self._lipsync.update(rms, centroid01, t_sec)

    def _handle_playback_end(self):
        self._lipsync.reset()
        self._mouth_shape = "closed"

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        self._stop_event.set()
        if self._video_proc and self._video_proc.poll() is None:
            self._video_proc.kill()
        if self._video_thread and self._video_thread.is_alive():
            self._video_thread.join(timeout=3)
