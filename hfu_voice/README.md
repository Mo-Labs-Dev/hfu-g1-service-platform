# G1 natural voice (Piper) — setup

`g1_voice_bridge.py` replaces `/ros2_ws/g1_speech_bridge.py`.
Same address (`127.0.0.1:8766`) and same `/speak` API, so the G1 Studio
backend keeps working. Voice: Piper neural TTS on the Jetson, German +
English, played through the G1's own speaker.

## One-time install (inside `g1pilot-dev`)

```bash
pip install piper-tts
cd /ros2_ws/src/g1pilot/hfu_voice/voices
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

Check voice licenses before public use (thorsten: CC0).

## Start (instead of g1_speech_bridge.py)

```bash
python3 /ros2_ws/src/g1pilot/hfu_voice/g1_voice_bridge.py
```

Expected: `[G1 Voice] Ready at http://127.0.0.1:8766  voice: Piper de+en`

Rollback: stop it and start the old `python3 g1_speech_bridge.py` again.

## Test

```bash
curl -s -X POST http://127.0.0.1:8766/speak -H 'Content-Type: application/json' \
  -d '{"text":"Hallo! Ich bin G1. Willkommen im Labor."}'
curl -s http://127.0.0.1:8766/status
curl -s -X POST http://127.0.0.1:8766/stop
```

## Options (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `G1_VOICE_DE` / `G1_VOICE_EN` | thorsten / lessac | voice file names in `voices/` |
| `G1_VOICE_LENGTH_SCALE` | `1.0` | `1.1` = slower, `0.9` = faster |
| `G1_VOICE_INTERFACE` | `enP2p1s0` | robot network interface |

## API

| Call | Body | Answer |
|---|---|---|
| `POST /speak` | `{"text", "lang"?: "de"/"en", "queue"?: true}` | `accepted, engine, lang, duration_ms, ends_in_ms` (409 if busy and no queue) |
| `GET /status` | – | `speaking, remaining_ms, queued, last_error` |
| `POST /stop` | – | stops playback, clears queue |
| `GET /health` | – | engine, loaded voices, voice errors |

`PlayStream` is rebuilt for the installed (older) unitree_sdk2py: one RPC
request (voice service, api 1003) carrying both the JSON parameter and the
16 kHz mono PCM, identical to the official `_CallRequestWithParamAndBin`.
