import os
from aiavatar_pi.device.pc import PCMotionClient

WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8000/ws")
CHARACTER_URL = os.getenv("CHARACTER_URL", "http://127.0.0.1:8000/static/motionpngtuber/miuna")

client = PCMotionClient(
    url=WEBSOCKET_URL,
    character_url=CHARACTER_URL,
    display_width=480,
    display_height=480,
    glow_config={
        "solid": 3,
        "corner_radius": 42,
        "opacity": 1.0,
    },
    lipsync_config={
        "cutoff_hz": 12.0,
        "rms_queue_max": 2,
        "peak_decay": 0.99,
    },
)

client.run()
