import asyncio
import base64
import io
import json
import logging
import queue
import threading
import array
import math
import time
import urllib.request
import wave
import websockets

from PIL import Image

from .audio import AudioBackend

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

logger = logging.getLogger(__name__)


class AIAvatarClientBase:
    def __init__(
        self,
        *,
        url: str = "ws://localhost:8000/ws",
        character_url: str = None,
        session_id: str = "ws_session",
        user_id: str = "ws_user",
        api_key: str = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 512,
        barge_in_enabled: bool = False,
        playback_chunk_size: int = 1024,
        audio_backend: AudioBackend = None
    ):
        self.url = url
        self.session_id = session_id
        self.user_id = user_id
        self.api_key = api_key

        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.playback_chunk_size = playback_chunk_size

        # Barge-in / mute control
        self.barge_in_enabled = barge_in_enabled
        self._user_muted = False
        self._is_server_processing = False
        self._is_barge_in_blocked = False

        # I/O Components
        self.audio_backend = audio_backend

        # Reconnection settings
        self.reconnect = True
        self.reconnect_interval = 3.0
        self.max_reconnect_interval = 60.0

        # Character assets
        self.character_url = character_url

        # Image caches
        self._face_pil_cache = {}
        self._mouth_pil_cache = {}

        # Callbacks
        self.on_face_updated = None      # func(face_name: str, face_duration: float)
        self.on_playback_analyze = None  # func(rms: float, centroid01: float, t_sec: float)
        self.on_playback_end = None      # func()
        self.on_voiced = None            # func()

        self._on_message = None          # func(msg: dict) | coroutine; called on every incoming WS message
        self._on_vision_requested = None  # func(source: str) | coroutine; called when vision is requested

        # Mute indicator (built lazily by subclass)
        self._mute_indicator = None

        self.ws = None
        self._is_playing = False
        self._play_queue = queue.Queue()
        self._play_stop_event = threading.Event()

        # Start playback worker
        self._play_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._play_thread.start()

    def on_message(self, func):
        """Register message handler as decorator.

        Usage::

            @client.on_message
            async def handle(msg: dict):
                ...
        """
        self._on_message = func
        return func

    def on_vision_requested(self, func):
        """Register vision request handler as decorator.

        Usage::

            @client.on_vision_requested
            async def handle(source: str):
                ...
        """
        self._on_vision_requested = func
        return func

    # ------------------------------------------------------------------
    # Microphone
    # ------------------------------------------------------------------
    async def _mic_worker(self):
        self.audio_backend.mic_open(
            self.sample_rate,
            self.channels,
            self.chunk_size
        )

        try:
            while True:
                data = self.audio_backend.mic_read(self.chunk_size, self.channels)
                if not data:
                    break
                if self._should_send_audio():
                    b64 = base64.b64encode(data).decode()
                    await self.ws.send(json.dumps({
                        "type": "data",
                        "session_id": self.session_id,
                        "audio_data": b64,
                    }))
                await asyncio.sleep(0.0001)
        finally:
            self.audio_backend.mic_close()

    def _should_send_audio(self) -> bool:
        if self._user_muted:
            return False
        if self._is_playing:
            self._is_server_processing = False
        if not self._is_playing and not self._is_server_processing:
            self._is_barge_in_blocked = False
        if self._is_barge_in_blocked:
            return False
        if self.barge_in_enabled:
            return True
        return not (self._is_playing or self._is_server_processing)

    # ------------------------------------------------------------------
    # Audio playback
    # ------------------------------------------------------------------
    def _playback_worker(self):
        while True:
            item = self._play_queue.get()
            if item is None:
                break
            audio_bytes, face_name, face_duration = item
            if face_name and self.on_face_updated:
                try:
                    self.on_face_updated(face_name, face_duration)
                except Exception:
                    pass
            self._is_playing = True
            try:
                self._play_wav(audio_bytes)
            except Exception as e:
                logger.error(f"Playback error: {e}")
            finally:
                self._is_playing = False
                if self.on_playback_end:
                    try:
                        self.on_playback_end()
                    except Exception:
                        pass

    def _play_wav(self, content: bytes):
        self._play_stop_event.clear()
        with wave.open(io.BytesIO(content), "rb") as wf:
            params = wf.getparams()
            self.audio_backend.player_open(
                params.nchannels,
                params.sampwidth,
                params.framerate
            )

            try:
                data = wf.readframes(self.playback_chunk_size)
                while data:
                    if self._play_stop_event.is_set():
                        break
                    if self.on_playback_analyze and params.sampwidth == 2:
                        rms, centroid01 = self._compute_audio_metrics(
                            data, params.sampwidth, params.framerate)
                        try:
                            self.on_playback_analyze(rms, centroid01, time.monotonic())
                        except Exception:
                            pass
                    self.audio_backend.player_write(data, self._play_stop_event.wait)
                    data = wf.readframes(self.playback_chunk_size)
            finally:
                self.audio_backend.player_close()

            if self.on_playback_analyze:
                try:
                    self.on_playback_analyze(0.0, 0.0, time.monotonic())
                except Exception:
                    pass

    def _compute_audio_metrics(self, data, sampwidth, sample_rate):
        if sampwidth != 2 or len(data) < 4:
            return 0.0, 0.0
        if _HAS_NUMPY:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(samples ** 2)))
            spectrum = np.abs(np.fft.rfft(samples))
            nyquist = sample_rate / 2
            freqs = np.linspace(0, nyquist, len(spectrum))
            den = float(np.sum(spectrum))
            centroid01 = min(1.0, float(np.sum(freqs * spectrum)) / den / nyquist) if den > 0 else 0.0
        else:
            samples = array.array("h", data)
            n = len(samples)
            sum_sq = sum(s * s for s in samples)
            rms = math.sqrt(sum_sq / n) / 32768.0
            centroid01 = 0.0
        return rms, centroid01

    def stop_playback(self):
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break
        self._play_stop_event.set()
        self.audio_backend.player_stop()

    # ------------------------------------------------------------------
    # WebSocket receive
    # ------------------------------------------------------------------
    async def _receive_worker(self):
        async for raw in self.ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            metadata = msg.get("metadata") or {}

            if self._on_message:
                try:
                    result = self._on_message(msg)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.warning(f"on_message error: {e}")

            if msg_type == "connected":
                self.user_id = msg.get("user_id", self.user_id)
                logger.info(f"Connected: session={msg.get('session_id')}, user={self.user_id}")

            elif msg_type == "voiced":
                if self.on_voiced:
                    try:
                        self.on_voiced()
                    except Exception:
                        pass

            elif msg_type == "accepted":
                self._is_server_processing = True
                if metadata.get("block_barge_in"):
                    self._is_barge_in_blocked = True

            elif msg_type == "start":
                request_text = metadata.get("request_text")
                if request_text:
                    logger.info(f"User: {request_text}")

            elif msg_type == "chunk":
                text = msg.get("text")
                if text:
                    logger.info(text)

                avreq = msg.get("avatar_control_request") or {}
                face_name = avreq.get("face_name")
                face_duration = avreq.get("face_duration", 2) if face_name else 0

                audio_b64 = msg.get("audio_data")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    self._play_queue.put((audio_bytes, face_name, face_duration))
                elif face_name and self.on_face_updated:
                    self.on_face_updated(face_name, face_duration)

            elif msg_type == "vision" and self._on_vision_requested:
                try:
                    result = self._on_vision_requested(metadata.get("source"))
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.warning(f"on_vision_requested error: {e}")

            elif msg_type == "final":
                self._is_server_processing = False
                voice_text = msg.get("voice_text") or msg.get("text")
                if voice_text:
                    logger.info(f"AI: {voice_text}")

            elif msg_type == "stop":
                self.stop_playback()
                if self.on_face_updated:
                    try:
                        self.on_face_updated("neutral", 0)
                    except Exception:
                        pass

            elif msg_type == "error":
                self._is_server_processing = False
                error = metadata.get("error", "Unknown error")
                logger.error(error)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    async def start(self):
        connect_kwargs = {}
        if self.api_key:
            connect_kwargs["additional_headers"] = {"Authorization": f"Bearer {self.api_key}"}

        interval = self.reconnect_interval

        while True:
            try:
                async with websockets.connect(self.url, **connect_kwargs) as ws:
                    self.ws = ws
                    interval = self.reconnect_interval  # reset on successful connect

                    await ws.send(json.dumps({
                        "type": "start",
                        "session_id": self.session_id,
                        "user_id": self.user_id,
                        "context_id": None,
                        "metadata": {"barge_in_enabled": self.barge_in_enabled},
                    }))

                    self._on_ws_connected()

                    mic_task = asyncio.create_task(self._mic_worker())
                    recv_task = asyncio.create_task(self._receive_worker())

                    try:
                        await asyncio.gather(mic_task, recv_task)
                    except (asyncio.CancelledError, KeyboardInterrupt):
                        raise
                    finally:
                        mic_task.cancel()
                        recv_task.cancel()
                        await self._stop_session(ws)

            except (asyncio.CancelledError, KeyboardInterrupt):
                break

            except Exception as e:
                self.ws = None
                self.stop_playback()
                self._is_server_processing = False

                if not self.reconnect:
                    raise

                logger.warning(f"Connection lost: {e}. Reconnecting in {interval:.1f}s...")
                await asyncio.sleep(interval)
                interval = min(interval * 2, self.max_reconnect_interval)

    def _on_ws_connected(self):
        """Called after WebSocket connection is established. Override in subclasses."""
        pass

    async def _stop_session(self, ws):
        try:
            await ws.send(json.dumps({
                "type": "stop",
                "session_id": self.session_id,
            }))
        except Exception:
            pass
        self.stop_playback()

    # ------------------------------------------------------------------
    # Mute control
    # ------------------------------------------------------------------
    def mute(self):
        self._user_muted = True

    def unmute(self):
        self._user_muted = False

    def toggle_mute(self) -> bool:
        self._user_muted = not self._user_muted
        return self._user_muted

    # ------------------------------------------------------------------
    # Mute indicator
    # ------------------------------------------------------------------
    def _build_mute_indicator(self, width, height):
        """Pre-compute mute indicator (red circle) for numpy RGB overlay."""
        if not _HAS_NUMPY:
            return

        radius = max(5, min(width, height) // 30)
        diameter = radius * 2 + 1
        margin = radius + 6

        y, x = np.ogrid[:diameter, :diameter]
        dist = np.sqrt((x - radius) ** 2 + (y - radius) ** 2)
        alpha = np.clip(radius + 0.5 - dist, 0, 1).astype(np.float32)

        self._mute_indicator = {
            "color": np.full((diameter, diameter, 3), [220, 50, 50], dtype=np.float32),
            "alpha": alpha[:, :, np.newaxis],
            "x": width - margin - radius,
            "y": margin - radius,
            "size": diameter,
        }

    def _overlay_mute_indicator(self, frame):
        """Draw mute indicator on numpy RGB frame if muted."""
        if not self._user_muted or self._mute_indicator is None:
            return

        ind = self._mute_indicator
        x, y, s = ind["x"], ind["y"], ind["size"]
        fh, fw = frame.shape[:2]

        sx, sy = max(0, -x), max(0, -y)
        ex, ey = min(s, fw - x), min(s, fh - y)
        if sx >= ex or sy >= ey:
            return

        a = ind["alpha"][sy:ey, sx:ex]
        c = ind["color"][sy:ey, sx:ex]
        fy0, fy1 = y + sy, y + ey
        fx0, fx1 = x + sx, x + ex
        frame[fy0:fy1, fx0:fx1] = (
            c * a + frame[fy0:fy1, fx0:fx1] * (1.0 - a)
        ).astype(np.uint8)

    # ------------------------------------------------------------------
    # Image cache
    # ------------------------------------------------------------------
    def _fetch_image(self, url):
        """Fetch image from URL and return as PIL Image."""
        resp = urllib.request.urlopen(url, timeout=5)
        return Image.open(io.BytesIO(resp.read()))

    def _get_face_pil(self, face_name):
        if face_name not in self._face_pil_cache:
            url = f"{self.character_url}/{face_name}.png"
            try:
                img = self._fetch_image(url)
                self._face_pil_cache[face_name] = img.convert("RGBA")
            except Exception as e:
                logger.warning(f"Failed to fetch face {url}: {e}")
                return None
        return self._face_pil_cache[face_name]

    def _get_mouth_pil(self, mouth_name):
        if mouth_name not in self._mouth_pil_cache:
            url = f"{self.character_url}/mouth_{mouth_name}.png"
            try:
                img = self._fetch_image(url)
                self._mouth_pil_cache[mouth_name] = img.convert("RGBA")
            except Exception as e:
                logger.warning(f"Failed to fetch mouth {url}: {e}")
                return None
        return self._mouth_pil_cache[mouth_name]
