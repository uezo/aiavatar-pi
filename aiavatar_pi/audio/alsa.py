from __future__ import annotations

import subprocess
import time
from typing import Callable, Optional

from .base import AudioBackend


class ALSABackend(AudioBackend):
    _ALSA_FORMATS = {1: "U8", 2: "S16_LE", 3: "S24_3LE", 4: "S32_LE"}

    def __init__(
        self,
        *,
        audio_device: Optional[str] = None,
        mixer_card: Optional[str] = None,
        mixer_control: Optional[str] = None,
    ):
        self.audio_device = audio_device
        self.mixer_card = mixer_card
        self.mixer_control = mixer_control

        self._mic_proc = None
        self._play_proc = None
        self._play_params = None
        self._bytes_per_sec = 0
        self._play_start = 0.0
        self._bytes_written = 0

    def mic_open(self, sample_rate: int, channels: int, chunk_size: int) -> None:
        cmd = [
            "arecord",
            "-f", "S16_LE",
            "-r", str(sample_rate),
            "-c", str(channels),
            "-t", "raw",
            "-q",
        ]
        if self.audio_device:
            cmd.extend(["-D", self.audio_device])
        try:
            self._mic_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "arecord not found. Install alsa-utils: sudo apt install alsa-utils"
            ) from e

    def mic_read(self, chunk_size: int, channels: int) -> bytes:
        n_bytes = chunk_size * channels * 2
        return self._mic_proc.stdout.read(n_bytes)

    def mic_close(self) -> None:
        if self._mic_proc:
            self._mic_proc.terminate()
            try:
                self._mic_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._mic_proc.kill()
            self._mic_proc = None

    def player_open(self, channels: int, sampwidth: int, framerate: int) -> None:
        params = (channels, sampwidth, framerate)
        if (self._play_proc is not None
                and self._play_proc.poll() is None
                and self._play_params == params):
            # Reuse existing aplay process, just reset pacing
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
        if self.audio_device:
            cmd.extend(["-D", self.audio_device])
        try:
            self._play_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "aplay not found. Install alsa-utils: sudo apt install alsa-utils"
            ) from e

        self._play_params = params
        self._bytes_per_sec = framerate * sampwidth * channels
        self._play_start = time.monotonic()
        self._bytes_written = 0

    def player_write(self, data: bytes, stop_waiter: Callable[[float], bool]) -> None:
        try:
            self._play_proc.stdin.write(data)
            self._play_proc.stdin.flush()
        except (BrokenPipeError, OSError):
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
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def player_stop(self) -> None:
        # Barge-in: kill immediately, force fresh open on next playback.
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
        try:
            subprocess.run(
                ["amixer", "-D", f"hw:{self.mixer_card}", "sset", self.mixer_control, level],
                capture_output=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    def cleanup(self) -> None:
        self.mic_close()
        self._kill_player()
