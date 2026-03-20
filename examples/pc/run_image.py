import os
from aiavatar_pi.device.pc import PCImageClient

WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8000/ws")
CHARACTER_URL = os.getenv("CHARACTER_URL", "http://127.0.0.1:8000/static/images")

client = PCImageClient(
    url=WEBSOCKET_URL,
    character_url=CHARACTER_URL,
    display_width=480,
    display_height=480,
)
client.run()
