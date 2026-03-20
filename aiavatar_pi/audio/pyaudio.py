"""PyAudio backend for desktop testing."""

from __future__ import annotations

import array
from typing import Callable

import pyaudio

from .base import AudioBackend


class PyAudioBackend(AudioBackend):
    def __init__(
        self,
        *,
        input_device_index: int | None = None,
        output_device_index: int | None = None,
        volume: float = 1.0,
    ):
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.volume = max(0.0, min(2.0, volume))

        self._pyaudio_mic = None
        self._mic_stream = None

        self._pyaudio_player = pyaudio.PyAudio()
        self._play_stream = None
        self._play_stream_params = None

    def mic_open(self, sample_rate: int, channels: int, chunk_size: int) -> None:
        self._pyaudio_mic = pyaudio.PyAudio()
        self._mic_stream = self._pyaudio_mic.open(
            rate=sample_rate,
            channels=channels,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=chunk_size,
            input_device_index=self.input_device_index,
        )

    def mic_read(self, chunk_size: int, channels: int) -> bytes:
        return self._mic_stream.read(chunk_size, exception_on_overflow=False)

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
            )
            self._play_stream_params = params
        elif self._play_stream.is_stopped():
            # Resume reused stream after a previous stop/barge-in.
            self._play_stream.start_stream()

    def player_write(self, data: bytes, stop_waiter: Callable[[float], bool]) -> None:
        if self.volume != 1.0:
            data = self._apply_volume(data)
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
        self.mic_close()
        if self._play_stream:
            self._play_stream.stop_stream()
            self._play_stream.close()
            self._play_stream = None
        if self._pyaudio_player:
            self._pyaudio_player.terminate()
            self._pyaudio_player = None

    def _apply_volume(self, data: bytes) -> bytes:
        gain = self.volume ** 2
        samples = array.array("h", data)
        for i in range(len(samples)):
            samples[i] = max(-32768, min(32767, int(samples[i] * gain)))
        return samples.tobytes()
