# aiavatar-pi

⚡️Ultra-low latency AI companion on edge devices.🍓 Talk to her anywhere, anytime.

aiavatar-pi connects to an [AIAvatarKit](https://github.com/uezo/aiavatarkit) server over WebSocket and renders an animated, talking avatar with lip sync on a Raspberry Pi with a small LCD, or on your desktop for development.

> This library is primarily designed for [Raspberry Pi Zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) with [Whisplay HAT](https://www.pisugar.com/products/whisplay-hat-for-pi-zero-2w-audio-display) hardware.

## ✨ Features

- 🍓 **Portable AI character** - Runs on Raspberry Pi + small SPI LCD, take it anywhere
- ⚡️ **Ultra-low latency voice** - Sub-second (<1 sec) response time for smooth, natural conversation
- 🥰 **Rich avatar expression** - Lip sync, auto blink, and video-based motion support
- 🧩 **Extensible hardware** - Swap displays, audio backends, and wire up GPIO buttons
- 🦞 **Agentic** - Unlimited extensibility with agentic capabilities, including [OpenClaw](https://openclaw.ai) integration

## 🏗️ Architecture

```
AIAvatarClientBase              ← WebSocket, audio I/O, playback control
├── AIAvatarImageClient         ← Face / blink / lip sync / glow state
│   ├── PiImageClient           ← SPI LCD + ALSA (Raspberry Pi)
│   │   └── WhisplayImageClient ← Whisplay hardware preset
│   └── PCImageClient           ← pygame + PyAudio (Desktop)
└── AIAvatarMotionClient        ← Video loop / mouth compositing / glow
    ├── PiMotionClient          ← SPI LCD + ALSA (Raspberry Pi)
    │   └── WhisplayMotionClient← Whisplay hardware preset
    └── PCMotionClient          ← pygame + PyAudio (Desktop)
```

## 🚀 Setup

Get started in 3 simple steps.

### 1. Start your AIAvatarKit server

See the [WebSocket quick start](https://github.com/uezo/aiavatarkit?tab=readme-ov-file#-websocket-browser) to get the server running. Make sure to use `--host 0.0.0.0` so the client can reach it over the network.

You'll need:

- WebSocket URL, e.g. `ws://192.168.1.1:8000/ws`
- Character asset URL, e.g. `http://192.168.1.1:8000/static/motionpngtuber/miuna`

### 2. Install

```bash
# Raspberry Pi (SPI LCD + ALSA)
sudo apt update && sudo apt install alsa-utils ffmpeg python3-dev build-essential
pip install "aiavatar-pi[pi]"

# PC (desktop, for development)
pip install "aiavatar-pi[pc]"
```

### 3. Write your client

Create a script (e.g. `run.py`) with one of the examples below, then run:

```sh
python run.py
```

**🍓 Whisplay — Motion avatar:**

```python
import asyncio
from aiavatar_pi.device.whisplay import WhisplayMotionClient

client = WhisplayMotionClient(
    character_url="http://192.168.1.1:8000/static/motionpngtuber/miuna",
    url="ws://192.168.1.1:8000/ws",
    volume=90,
)

@client.button.on_press
def on_press():
    client.toggle_mute()

try:
    asyncio.run(client.start())
except KeyboardInterrupt:
    pass
finally:
    client.cleanup()
```

**🍓 Whisplay — Image avatar:**

```python
import asyncio
from aiavatar_pi.device.whisplay import WhisplayImageClient

client = WhisplayImageClient(
    character_url="http://192.168.1.1:8000/static/images",
    url="ws://192.168.1.1:8000/ws",
    volume=90,
)

@client.button.on_press
def on_press():
    client.toggle_mute()

try:
    asyncio.run(client.start())
except KeyboardInterrupt:
    pass
finally:
    client.cleanup()
```

**🍓 Raspberry Pi — Custom hardware (motion avatar):**

For display options beyond ST7789, see [Display Support](#-display-support).

```python
import asyncio
from aiavatar_pi.device.pi import PiMotionClient
from aiavatar_pi.display.st7789 import ST7789

client = PiMotionClient(
    character_url="http://192.168.1.1:8000/static/motionpngtuber/miuna",
    url="ws://192.168.1.1:8000/ws",
    lcd=ST7789(width=240, height=320, backlight=80),
    # typical for Raspberry Pi 3.5mm jack and USB microphone
    input_device="plughw:1,0",   # USB Microphone
    output_device="plughw:0,0",  # 3.5 mm stereo jack
    mixer_card="0",
    mixer_control="PCM",
    # buttons=[GPIOButton(pin=17)],  # optional
    volume=90,
)

try:
    asyncio.run(client.start())
except KeyboardInterrupt:
    pass
finally:
    client.cleanup()
```

**🍓 Raspberry Pi — Custom hardware (image avatar):**

```python
import asyncio
from aiavatar_pi.device.pi import PiImageClient
from aiavatar_pi.display.st7789 import ST7789

client = PiImageClient(
    character_url="http://192.168.1.1:8000/static/images",
    url="ws://192.168.1.1:8000/ws",
    lcd=ST7789(width=240, height=320, backlight=80),
    # typical for Raspberry Pi 3.5mm jack and USB microphone
    input_device="plughw:1,0",   # USB Microphone
    output_device="plughw:0,0",  # 3.5 mm stereo jack
    mixer_card="0",
    mixer_control="PCM",
    # buttons=[GPIOButton(pin=17)],  # optional
    volume=90,
)

try:
    asyncio.run(client.start())
except KeyboardInterrupt:
    pass
finally:
    client.cleanup()
```

**🖥️ PC — Motion avatar (for development):**

```python
from aiavatar_pi.device.pc import PCMotionClient

client = PCMotionClient(
    character_url="http://192.168.1.1:8000/static/motionpngtuber/miuna",
    url="ws://192.168.1.1:8000/ws",
    display_width=480,
    display_height=480,
)
client.run()
```

**🖥️ PC — Image avatar (for development):**

```python
from aiavatar_pi.device.pc import PCImageClient

client = PCImageClient(
    character_url="http://192.168.1.1:8000/static/images",
    url="ws://192.168.1.1:8000/ws",
    display_width=480,
    display_height=480,
)
client.run()
```

## 🎨 Customize

**Lip sync tuning:**

```python
client = PCMotionClient(
    ...,
    lipsync_config={
        "cutoff_hz": 12.0,       # Higher = faster response (default: 8.0)
        "rms_queue_max": 2,      # Lower = less latency (default: 3)
        "peak_decay": 0.99,      # Lower = faster volume tracking (default: 0.995)
    },
)
```

**Glow effect:**

```python
client = PCMotionClient(
    ...,
    glow_config={
        "solid": 3,              # Border width in px
        "corner_radius": 42,     # Rounded corner radius
        "opacity": 1.0,          # 0.0 to 1.0
    },
)
```

**Swap audio backend:**

```python
from aiavatar_pi.audio.pyaudio import PyAudioBackend

client = WhisplayMotionClient(
    ...,
    audio_backend=PyAudioBackend(volume=0.8),
)
```

## 📋 Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `url` | `ws://localhost:8000/ws` | WebSocket server URL |
| `character_url` | `None` | Base URL for character assets (faces, mouth sprites, video) |
| `api_key` | `None` | Bearer token for authentication |
| `sample_rate` | `16000` | Mic sample rate (Hz) |
| `channels` | `1` | Mic channels |
| `barge_in_enabled` | `False` | Allow interrupting AI speech |
| `volume` | `100` (Whisplay) | Playback volume (%) |
| `mixer_card` | `None` | ALSA mixer card for volume control (Raspberry Pi only, e.g. `"0"`) |
| `mixer_control` | `None` | ALSA mixer control name (Raspberry Pi only, e.g. `"PCM"`) |
| `audio_backend` | `None` (auto) | Custom audio backend |


## 🖥️ Display Support

`PiImageClient` and `PiMotionClient` accept any display driver via the `lcd=` parameter. Built-in drivers:

| Driver | Interface | Pixel Format | Typical Use |
|--------|-----------|-------------|-------------|
| `ST7789` | SPI (userspace) | RGB565 | 1.3"–2.4" small displays |
| `ILI9488` | SPI (userspace) | RGB666 | 3.5" displays (320x480) |
| `FramebufferDisplay` | Linux framebuffer | RGB565 | Any display with fbtft/DRM kernel driver |

### ST7789 (default)

Works out of the box. No kernel driver needed.

```python
from aiavatar_pi.display.st7789 import ST7789
lcd = ST7789(width=240, height=320, spi_speed_hz=100_000_000, backlight=80)
```

### ILI9488 (SPI direct)

Uses RGB666 (3 bytes/pixel) over userspace SPI. Simple to set up, but large displays (480x320) may have slow frame rates due to SPI transfer bottleneck.

```python
from aiavatar_pi.display.ili9488 import ILI9488
lcd = ILI9488(width=320, height=480, dc_pin=18, rst_pin=22, spi_speed_hz=24_000_000)
```

Pin numbers use BOARD numbering (not BCM). Default SPI speed is 24 MHz.

### FramebufferDisplay (DMA, for large displays)

Writes to a Linux framebuffer device (`/dev/fb1`). The kernel fbtft driver handles SPI transfer via DMA — much faster than userspace SPI.

```python
from aiavatar_pi.display.framebuffer import FramebufferDisplay
lcd = FramebufferDisplay(fb_device="/dev/fb1", width=480, height=320)
```

**Requires kernel-level setup.** Example using the built-in `piscreen` overlay (ILI9488):

1. Add to `/boot/firmware/config.txt` under `[all]`:
   ```
   dtparam=spi=on
   dtoverlay=piscreen,speed=48000000,rotate=90
   ```
2. Reboot and verify: `ls /dev/fb1`

> **Note:** The fbtft kernel driver and overlay configuration are display-specific and outside the scope of this project. Color accuracy, rotation, and performance depend on the overlay and kernel module used. Refer to your display's documentation for the correct setup.

### Custom display drivers

You can create a custom driver by subclassing `DisplayDriver` (for framebuffer-like devices) or `SPIDisplay` (for SPI-connected displays). See the [source code](aiavatar_pi/display/) for reference implementations.
