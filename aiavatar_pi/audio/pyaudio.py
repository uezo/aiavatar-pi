"""PyAudio backend for desktop testing."""

from __future__ import annotations

import array
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pyaudio

from .base import AudioBackend

logger = logging.getLogger(__name__)


class PyAudioBackend(AudioBackend):
    def __init__(
        self,
        *,
        input_device_index: int | None = None,
        output_device_index: int | None = None,
        volume: float = 1.0,
        playback_buffer_size: int = 2048,
    ):
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.volume = max(0.0, min(2.0, volume))
        self.playback_buffer_size = playback_buffer_size

        self._pyaudio_mic = None
        self._mic_stream = None
        self._mic_target_rate = 0
        self._mic_actual_rate = 0

        self._pyaudio_player = pyaudio.PyAudio()
        self._play_stream = None
        self._play_stream_params = None
        self._before_play: Callable[[bytes, int, int, int], None] | None = None
        self._hook_executor = ThreadPoolExecutor(max_workers=1)

    def before_play(self, func: Callable[[bytes, int, int, int], None]):
        self._before_play = func
        return func

    def mic_open(self, sample_rate: int, channels: int, chunk_size: int) -> None:
        self._pyaudio_mic = pyaudio.PyAudio()
        self._mic_target_rate = sample_rate
        self._mic_actual_rate = sample_rate

        # Log device info
        if self.input_device_index is not None:
            info = self._pyaudio_mic.get_device_info_by_index(self.input_device_index)
        else:
            info = self._pyaudio_mic.get_default_input_device_info()
        logger.info(
            "Mic device %d: %s (default rate=%dHz)",
            int(info["index"]), info["name"], int(info["defaultSampleRate"]),
        )

        try:
            self._mic_stream = self._pyaudio_mic.open(
                rate=sample_rate,
                channels=channels,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=chunk_size,
                input_device_index=self.input_device_index,
            )
            logger.info("Mic opened at %dHz", sample_rate)
        except OSError as e:
            logger.warning("Cannot open mic at %dHz: %s", sample_rate, e)
            actual_rate = int(info["defaultSampleRate"])
            actual_chunk = int(chunk_size * actual_rate / sample_rate)
            self._mic_stream = self._pyaudio_mic.open(
                rate=actual_rate,
                channels=channels,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=actual_chunk,
                input_device_index=self.input_device_index,
            )
            self._mic_actual_rate = actual_rate
            logger.info("Mic opened at %dHz (will resample to %dHz)", actual_rate, sample_rate)

    def mic_read(self, chunk_size: int, channels: int) -> bytes:
        if self._mic_actual_rate == self._mic_target_rate:
            return self._mic_stream.read(chunk_size, exception_on_overflow=False)

        # Read proportionally more frames, then downsample
        actual_frames = int(chunk_size * self._mic_actual_rate / self._mic_target_rate)
        data = self._mic_stream.read(actual_frames, exception_on_overflow=False)
        return self._resample(data, channels, self._mic_actual_rate, self._mic_target_rate)

    def mic_close(self) -> None:
        if self._mic_stream:
            self._mic_stream.stop_stream()
            self._mic_stream.close()
            self._mic_stream = None
        if self._pyaudio_mic:
            self._pyaudio_mic.terminate()
            self._pyaudio_mic = None

    def player_open(self, channels: int, sampwidth: int, framerate: int) -> None:
        params = (channels, sampwidth, framerate)
        if self._play_stream is None or self._play_stream_params != params:
            if self._play_stream:
                self._play_stream.stop_stream()
                self._play_stream.close()
            self._play_stream = self._pyaudio_player.open(
                format=self._pyaudio_player.get_format_from_width(sampwidth),
                channels=channels,
                rate=framerate,
                output=True,
                output_device_index=self.output_device_index,
                frames_per_buffer=self.playback_buffer_size,
            )
            self._play_stream_params = params
        elif self._play_stream.is_stopped():
            # Resume reused stream after a previous stop/barge-in.
            self._play_stream.start_stream()

    def player_write(self, data: bytes, stop_waiter: Callable[[float], bool]) -> None:
        if self.volume != 1.0:
            data = self._apply_volume(data)
        if self._before_play:
            channels, sampwidth, framerate = self._play_stream_params
            self._hook_executor.submit(self._before_play, data, framerate, channels, sampwidth)
        self._play_stream.write(data)

    def player_close(self) -> None:
        # Keep stream open for same format reuse.
        pass

    def player_stop(self) -> None:
        # Don't touch the stream. Base class already stops writing via
        # _play_stop_event.  Keeping the stream alive avoids pop/click
        # noise from close/reopen (matches AudioPlayer.stop() pattern).
        pass

    def set_volume(self, level) -> None:
        if isinstance(level, (int, float)):
            if level > 2.0:
                self.volume = max(0.0, min(2.0, float(level) / 100.0 * 2.0))
            else:
                self.volume = max(0.0, min(2.0, float(level)))

    def cleanup(self) -> None:
        self._hook_executor.shutdown(wait=False)
        self.mic_close()
        if self._play_stream:
            self._play_stream.stop_stream()
            self._play_stream.close()
            self._play_stream = None
        if self._pyaudio_player:
            self._pyaudio_player.terminate()
            self._pyaudio_player = None

    @staticmethod
    def _resample(data: bytes, channels: int, from_rate: int, to_rate: int) -> bytes:
        src = array.array("h", data)
        n_frames = len(src) // channels
        dst_frames = int(n_frames * to_rate / from_rate)
        dst = array.array("h")
        for i in range(dst_frames):
            pos = i * from_rate / to_rate
            idx = int(pos)
            frac = pos - idx
            for ch in range(channels):
                s0 = src[idx * channels + ch]
                if idx + 1 < n_frames:
                    s1 = src[(idx + 1) * channels + ch]
                else:
                    s1 = s0
                dst.append(max(-32768, min(32767, int(s0 + (s1 - s0) * frac))))
        return dst.tobytes()

    def _apply_volume(self, data: bytes) -> bytes:
        gain = self.volume ** 2
        samples = array.array("h", data)
        for i in range(len(samples)):
            samples[i] = max(-32768, min(32767, int(samples[i] * gain)))
        return samples.tobytes()
