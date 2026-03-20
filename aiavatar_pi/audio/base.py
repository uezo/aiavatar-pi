"""Audio backend interfaces."""

from __future__ import annotations

from typing import Callable


class AudioBackend:
    def mic_open(self, sample_rate: int, channels: int, chunk_size: int) -> None:
        raise NotImplementedError

    def mic_read(self, chunk_size: int, channels: int) -> bytes:
        raise NotImplementedError

    def mic_close(self) -> None:
        raise NotImplementedError

    def player_open(self, channels: int, sampwidth: int, framerate: int) -> None:
        raise NotImplementedError

    def player_write(self, data: bytes, stop_waiter: Callable[[float], bool]) -> None:
        raise NotImplementedError

    def player_close(self) -> None:
        raise NotImplementedError

    def player_stop(self) -> None:
        pass

    def set_volume(self, level) -> None:
        pass

    def cleanup(self) -> None:
        pass
