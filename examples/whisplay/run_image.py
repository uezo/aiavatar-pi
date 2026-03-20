import asyncio
import os
import logging
from aiavatar_pi.device.whisplay import WhisplayImageClient

WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8000/ws")
CHARACTER_URL = os.getenv("CHARACTER_URL", "http://127.0.0.1:8000/static/images")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
log_format = logging.Formatter("[%(levelname)s] %(asctime)s : %(message)s")
streamHandler = logging.StreamHandler()
streamHandler.setFormatter(log_format)
logger.addHandler(streamHandler)

client = WhisplayImageClient(
    url=WEBSOCKET_URL,
    character_url=CHARACTER_URL,
    volume=90,
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
