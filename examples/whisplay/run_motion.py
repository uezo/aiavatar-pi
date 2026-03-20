import asyncio
import os
import logging
from aiavatar_pi.device.whisplay import WhisplayMotionClient

WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8000/ws")
CHARACTER_URL = os.getenv("CHARACTER_URL", "http://127.0.0.1:8000/static/motionpngtuber/miuna")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
log_format = logging.Formatter("[%(levelname)s] %(asctime)s : %(message)s")
streamHandler = logging.StreamHandler()
streamHandler.setFormatter(log_format)
logger.addHandler(streamHandler)

client = WhisplayMotionClient(
    url=WEBSOCKET_URL,
    character_url=CHARACTER_URL,
    volume=90,
    glow_config={
        "solid": 3,             # Border width (px)
        "corner_radius": 42,    # Rounded corner radius
        "opacity": 1.0,         # Opacity (0.0 to 1.0)
    },
    lipsync_config={
        "cutoff_hz": 12.0,      # Higher = faster response (default: 8.0)
        "rms_queue_max": 2,     # Lower = less latency (default: 3)
        "peak_decay": 0.99,     # Lower = faster volume tracking (default: 0.995)
    },
)

@client.button.on_press
def on_press():
    print("Button pressed!")
    client.toggle_mute()

try:
    asyncio.run(client.start())
except KeyboardInterrupt:
    print("\nDisconnected.")
finally:
    client.cleanup()
