from __future__ import annotations

import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .base import AudioBackend

logger = logging.getLogger(__name__)


class ALSABackend(AudioBackend):
    _ALSA_FORMATS = {1: "U8", 2: "S16_LE", 3: "S24_3LE", 4: "S32_LE"}

    def __init__(
        self,
        *,
        input_device: Optional[str] = None,
        output_device: Optional[str] = None,
        mixer_card: Optional[str] = None,
        mixer_control: Optional[str] = None,
        playback_buffer_size: Optional[int] = None,
    ):
        self.input_device = input_device
        self.output_device = output_device
        self.mixer_card = mixer_card
        self.mixer_control = mixer_control
        self.playback_buffer_size = playback_buffer_size

        self._mic_proc = None
        self._play_proc = None
        self._play_params = None
        self._bytes_per_sec = 0
        self._play_start = 0.0
        self._bytes_written = 0
        self._before_play: Callable[[bytes, int, int, int], None] | None = None
        self._hook_executor = ThreadPoolExecutor(max_workers=1)

    def before_play(self, func: Callable[[bytes, int, int, int], None]):
        self._before_play = func
        return func

    def mic_open(self, sample_rate: int, channels: int, chunk_size: int) -> None:
        cmd = [
            "arecord",
            "-f", "S16_LE",
            "-r", str(sample_rate),
            "-c", str(channels),
            "-t", "raw",
            "-q",
        ]
        if self.input_device:
            cmd.extend(["-D", self.input_device])
        logger.info(
            "Mic opening: device=%s, rate=%dHz, channels=%d, chunk=%d",
            self.input_device or "default", sample_rate, channels, chunk_size,
        )
        try:
            self._mic_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "arecord not found. Install alsa-utils: sudo apt install alsa-utils"
            ) from e
        logger.info("Mic opened (arecord pid=%d)", self._mic_proc.pid)

    def mic_read(self, chunk_size: int, channels: int) -> bytes:
        n_bytes = chunk_size * channels * 2
        return self._mic_proc.stdout.read(n_bytes)

    def mic_close(self) -> None:
        if self._mic_proc:
            logger.info("Mic closing (arecord pid=%d)", self._mic_proc.pid)
            self._mic_proc.terminate()
            try:
                self._mic_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.warning("arecord did not exit in time, killing")
                self._mic_proc.kill()
            self._mic_proc = None

    def player_open(self, channels: int, sampwidth: int, framerate: int) -> None:
        params = (channels, sampwidth, framerate)
        if (self._play_proc is not None
                and self._play_proc.poll() is None
                and self._play_params == params):
            # Reuse existing aplay process, just reset pacing
            logger.debug("Reusing aplay process (pid=%d)", self._play_proc.pid)
            self._play_start = time.monotonic()
            self._bytes_written = 0
            return

        # Different format or no process, start fresh
        self._kill_player()
        fmt = self._ALSA_FORMATS.get(sampwidth, "S16_LE")
        cmd = [
            "aplay",
            "-f", fmt,
            "-r", str(framerate),
            "-c", str(channels),
            "-t", "raw",
            "-q",
        ]
        if self.output_device:
            cmd.extend(["-D", self.output_device])
        if self.playback_buffer_size:
            cmd.extend(["--buffer-size", str(self.playback_buffer_size)])
        logger.info(
            "Player opening: device=%s, format=%s, rate=%dHz, channels=%d",
            self.output_device or "default", fmt, framerate, channels,
        )
        try:
            self._play_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "aplay not found. Install alsa-utils: sudo apt install alsa-utils"
            ) from e
        logger.info("Player opened (aplay pid=%d)", self._play_proc.pid)

        self._play_params = params
        self._bytes_per_sec = framerate * sampwidth * channels
        self._play_start = time.monotonic()
        self._bytes_written = 0

    def player_write(self, data: bytes, stop_waiter: Callable[[float], bool]) -> None:
        if self._before_play and self._play_params:
            channels, sampwidth, framerate = self._play_params
            self._hook_executor.submit(self._before_play, data, framerate, channels, sampwidth)
        try:
            self._play_proc.stdin.write(data)
            self._play_proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.warning("Player write failed: %s", e)
            return

        self._bytes_written += len(data)
        expected = self._bytes_written / self._bytes_per_sec
        elapsed = time.monotonic() - self._play_start
        sleep_time = expected - elapsed
        if sleep_time > 0.001:
            stop_waiter(sleep_time)

    def player_close(self) -> None:
        # Close stdin so aplay flushes its buffer and exits gracefully.
        # This ensures all audio is played before mic reopens (no loopback).
        proc = self._play_proc
        self._play_proc = None
        self._play_params = None
        if proc and proc.poll() is None:
            logger.info("Player closing (aplay pid=%d)", proc.pid)
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.warning("aplay did not exit in time, killing")
                proc.kill()

    def player_stop(self) -> None:
        # Barge-in: kill immediately, force fresh open on next playback.
        logger.info("Player stopping (barge-in)")
        self._kill_player()

    def _kill_player(self) -> None:
        proc = self._play_proc
        self._play_proc = None
        self._play_params = None
        if proc and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def set_volume(self, level) -> None:
        if not self.mixer_card or not self.mixer_control:
            return
        if isinstance(level, (int, float)):
            level = f"{int(level)}%"
        logger.info("Setting volume: %s %s = %s", self.mixer_card, self.mixer_control, level)
        try:
            subprocess.run(
                ["amixer", "-D", f"hw:{self.mixer_card}", "sset", self.mixer_control, level],
                capture_output=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logger.warning("Failed to set volume: %s", e)

    def cleanup(self) -> None:
        self._hook_executor.shutdown(wait=False)
        self.mic_close()
        self._kill_player()
