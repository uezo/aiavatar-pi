"""GPIO button with polling."""

import threading

import RPi.GPIO as GPIO


class GPIOButton:
    def __init__(self, pin=11, pull=GPIO.PUD_OFF):
        self._pin = pin
        GPIO.setup(pin, GPIO.IN, pull_up_down=pull)
        self._on_press = None
        self._on_release = None
        self._last_state = GPIO.input(pin)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self):
        while not self._stop_event.is_set():
            state = GPIO.input(self._pin)
            if state != self._last_state:
                self._last_state = state
                if state:  # HIGH = pressed
                    if self._on_press:
                        self._on_press()
                else:  # LOW = released
                    if self._on_release:
                        self._on_release()
            self._stop_event.wait(timeout=0.01)

    def on_press(self, callback):
        self._on_press = callback
        return callback

    def on_release(self, callback):
        self._on_release = callback
        return callback

    def cleanup(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
