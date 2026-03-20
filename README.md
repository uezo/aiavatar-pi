# aiavatar-pi

⚡️Ultra-low latency AI companion on edge devices.🍓 Talk to her anywhere, anytime.

aiavatar-pi connects to an [AIAvatarKit](https://github.com/uezo/aiavatarkit) server over WebSocket and renders an animated, talking avatar with lip sync on a Raspberry Pi with a small LCD, or on your desktop for development.

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
sudo apt install alsa-utils ffmpeg
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

**🍓 Raspberry Pi — Custom hardware:**

```python
import asyncio
from aiavatar_pi.device.pi import PiMotionClient
from aiavatar_pi.display.st7789 import ST7789
from aiavatar_pi.button import GPIOButton

client = PiMotionClient(
    character_url="http://192.168.1.1:8000/static/motionpngtuber/miuna",
    url="ws://192.168.1.1:8000/ws",
    lcd=ST7789(width=240, height=320, backlight=80),  # display resolution and brightness
    # buttons=[GPIOButton(pin=17)],  # optional, add if you have buttons
    # input_device="plughw:1,0"   # USB Microphone
    # output_device="plughw:0,0"  # 3.5 mm stereo jack
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
| `audio_backend` | `None` (auto) | Custom audio backend |
