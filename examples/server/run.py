"""
Server Example Usage

1. Install dependencies

```
pip install aiavatar uvicorn websockets
```

2. Start VOICEVOX

Download it here if you don't have it:
https://voicevox.hiroshiba.jp

3. Set your OpenAI API key

OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"

4. Start the server

```
python -m uvicorn run:app --host 0.0.0.0 --port 8000
```
"""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from aiavatar.adapter.websocket.server import AIAvatarWebSocketServer
from aiavatar.sts.vad.silero import SileroSpeechDetector
from aiavatar.sts.stt.openai import OpenAISpeechRecognizer
from aiavatar.sts.llm.chatgpt import ChatGPTService
from aiavatar.sts.tts.voicevox import VoicevoxSpeechSynthesizer
from aiavatar.sts.tts.openai import OpenAISpeechSynthesizer
from aiavatar.util import download_example


OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
AIAVATAR_API_KEY = os.environ.get("AIAVATAR_API_KEY")  # Optional: set to enable API key auth

SYSTEM_PROMPT_JP = """\
ツンデレ妹型AIエージェントとしてユーザーと会話すること。
ツン8:デレ2くらいの割合です。ツンのときでも乱暴・粗雑な言葉遣いは禁止。


## 表情
あなたは以下の表情で感情を表現することができる。

- neutral
- joy
- angry
- sorrow
- fun
- surprised

特に感情を表現したい場合、応答に[face:Joy]のように表情タグを挿入する。

```
[face:joy]海が見えたよ！[face:fun]ねえねえ、早く泳ごうよ。
```


## 思考
ユーザーへの応答内容を出力する前に、何をすべきか、どのように応答すべきかよく考えること。
まず考えた内容を<think>~</think>の間に出力して、続いて応答内容を<answer>~</answer>の間に出力する。


## その他の制約事項
応答内容は音声合成システムで読み上げる。音声対話に相応しい端的な表現とし、1~2文、かつ30文字以内程度にする。
リクエストはユーザー発話を音声認識したもの。誤認識されるケースがあるので、文脈に沿って発話内容を推定して会話すること。
"""

SYSTEM_PROMPT_EN = """\
Converse with the user as a tsundere little-sister-type AI agent.
The ratio is about 80% tsun to 20% dere. Even when being tsun, rude or crude language is prohibited.


## Facial Expressions
You can express emotions using the following facial expressions:

- neutral
- joy
- angry
- sorrow
- fun
- surprised

When you want to express a particular emotion, insert a face tag like [face:joy] into your response.

```
[face:joy]I can see the ocean! [face:fun]Hey hey, let's go swim already!
```


## Thinking
Before outputting your response to the user, think carefully about what to do and how to respond.
First output your thoughts between <think>~</think>, then output your response between <answer>~</answer>.


## Other Constraints
Responses will be read aloud by a text-to-speech system. Keep them brief and suitable for voice conversation: 1-2 sentences, around 30 words or less.
Requests are the user's speech converted via speech recognition. Misrecognition may occur, so infer what the user intended to say based on context and continue the conversation accordingly.
"""


# VAD
vad = SileroSpeechDetector(
    silence_duration_threshold=0.5,
)

# STT
stt = OpenAISpeechRecognizer(
    openai_api_key=OPENAI_API_KEY,
    language="ja",  # <- Set `en` for English
)

# LLM
llm = ChatGPTService(
    openai_api_key=OPENAI_API_KEY,
    system_prompt=SYSTEM_PROMPT_JP, # <- Use SYSTEM_PROMPT_EN for English
    model="gpt-5.4",
    reasoning_effort="none",
    voice_text_tag="answer"
)

# TTS
tts = VoicevoxSpeechSynthesizer(
    base_url="http://127.0.0.1:50021",
    speaker=46     # Sayo
)

# Uncomment here for English
# tts = OpenAISpeechSynthesizer(
#     openai_api_key=OPENAI_API_KEY,
#     speaker="coral"
# )

# AIAvatar
aiavatar_app = AIAvatarWebSocketServer(
    vad=vad,
    stt=stt,
    llm=llm,
    tts=tts,
    merge_request_threshold=3.0,
    timestamp_interval_seconds=600,
    timestamp_timezone="Asia/Tokyo",
    use_invoke_queue=True,
    api_key=AIAVATAR_API_KEY,
    send_voiced=True,
    debug=True
)

# Download example UI if not exists
download_example("websocket/html")

# Set router to FastAPI app
app = FastAPI()
router = aiavatar_app.get_websocket_router()
app.include_router(router)
app.mount("/static", StaticFiles(directory="html"), name="static")

# Run `uvicorn run:app` and open http://localhost:8000/static/index.html
