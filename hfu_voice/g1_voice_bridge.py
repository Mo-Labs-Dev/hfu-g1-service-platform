#!/usr/bin/env python3
"""
G1 Studio natural voice bridge (drop-in replacement for g1_speech_bridge.py).

Same address and API as before:
    POST http://127.0.0.1:8766/speak   {"text": "..."}
    GET  http://127.0.0.1:8766/health

New:
    POST /speak  optional fields:
        "lang":  "de" | "en"   (default: detected from the text)
        "queue": true          (append to the queue instead of 409 when busy)
      response adds: "engine", "lang", "duration_ms"
    GET  /status  -> {"speaking": bool, "remaining_ms": int, "queued": int}
    POST /stop    -> stops playback and clears the queue

Voice: Piper neural TTS (offline, on the Jetson), German + English.
Audio goes to the G1's own speaker via the voice service "PlayStream"
call, rebuilt here because the installed unitree_sdk2py is too old to
have it. If Piper is unavailable, it falls back to the built-in TtsMaker.

No locomotion, arm, or FSM commands are implemented here.
"""
from __future__ import annotations

import io
import json
import os
import queue
import re
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.getenv("G1_VOICE_HOST", "127.0.0.1")
PORT = int(os.getenv("G1_VOICE_PORT", "8766"))
INTERFACE = os.getenv("G1_VOICE_INTERFACE", "enP2p1s0")
MAX_TEXT_LENGTH = 450
MAX_QUEUE = 8

VOICE_DIR = os.getenv(
    "G1_VOICE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
)
VOICE_MODELS = {
    "de": os.getenv("G1_VOICE_DE", "de_DE-thorsten-medium.onnx"),
    "en": os.getenv("G1_VOICE_EN", "en_US-lessac-medium.onnx"),
}
# Speaking speed: >1.0 slower, <1.0 faster (Piper length_scale).
LENGTH_SCALE = float(os.getenv("G1_VOICE_LENGTH_SCALE", "1.0"))

# G1 voice service (official unitree_sdk2py g1/audio/g1_audio_api.py).
AUDIO_SERVICE_NAME = "voice"
AUDIO_API_VERSION = "1.0.0.0"
API_TTS = 1001
API_START_PLAY = 1003
API_STOP_PLAY = 1004
API_GET_VOLUME = 1005
API_SET_VOLUME = 1006

PLAY_RATE = 16000            # G1 speaker stream: 16 kHz, mono, 16-bit
APP_NAME = "g1studio"
CHUNK_BYTES = 96000          # 3 s of audio per PlayStream call
CHUNK_PAUSE = 1.0            # as in Unitree's PCM stream example
END_MARGIN = 0.4             # s added to the estimated end of speech


# ----------------------------------------------------------------------
# Language detection (German vs English) - simple and fast
# ----------------------------------------------------------------------

_GERMAN_WORDS = {
    "und", "ich", "nicht", "ist", "das", "die", "der", "ein", "eine", "sie",
    "wir", "du", "mit", "auf", "für", "fuer", "bitte", "danke", "hallo",
    "willkommen", "ja", "nein", "gerne", "labor", "hier", "wie", "was",
    "wo", "heute", "sind", "bin", "zu", "den", "dem", "auch", "noch",
    "gibt", "kann", "können", "koennen", "möchte", "moechte", "schön",
}


def detect_language(text: str) -> str:
    lowered = text.lower()
    if re.search(r"[äöüß]", lowered):
        return "de"
    words = re.findall(r"[a-zäöüß]+", lowered)
    german = sum(1 for w in words if w in _GERMAN_WORDS)
    return "de" if german >= 2 or (words and german / len(words) > 0.2) else "en"


# ----------------------------------------------------------------------
# Audio helpers
# ----------------------------------------------------------------------

def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int = PLAY_RATE) -> bytes:
    """Mono int16 PCM resampling (polyphase if SciPy exists, else linear)."""
    import numpy as np

    if src_rate == dst_rate or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(src_rate, dst_rate)
        out = resample_poly(samples, dst_rate // g, src_rate // g)
    except Exception:
        n_out = int(round(len(samples) * dst_rate / src_rate))
        x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        out = np.interp(x_new, x_old, samples)
    return np.clip(out, -32768, 32767).astype(np.int16).tobytes()


def pcm_duration(pcm: bytes, rate: int = PLAY_RATE) -> float:
    return len(pcm) / 2.0 / rate


# ----------------------------------------------------------------------
# Piper TTS
# ----------------------------------------------------------------------

class PiperTTS:
    """Loads one Piper voice per language; returns 16 kHz mono PCM."""

    def __init__(self) -> None:
        self.voices: dict[str, object] = {}
        self.errors: dict[str, str] = {}
        try:
            from piper import PiperVoice  # pip install piper-tts
        except Exception as exc:
            self.errors["piper"] = f"piper-tts not installed: {exc}"
            return
        for lang, name in VOICE_MODELS.items():
            path = name if os.path.isabs(name) else os.path.join(VOICE_DIR, name)
            try:
                self.voices[lang] = PiperVoice.load(path)
                print(f"[G1 Voice] Loaded {lang} voice: {path}", flush=True)
            except Exception as exc:
                self.errors[lang] = f"{path}: {exc}"
                print(f"[G1 Voice] Could not load {lang} voice: {exc}", flush=True)

    def available(self, lang: str) -> bool:
        return lang in self.voices

    def synthesize(self, text: str, lang: str) -> bytes:
        voice = self.voices[lang]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            if hasattr(voice, "synthesize_wav"):          # piper-tts >= 1.3
                try:
                    from piper import SynthesisConfig

                    cfg = SynthesisConfig(length_scale=LENGTH_SCALE)
                    voice.synthesize_wav(text, wav, syn_config=cfg)
                except Exception:
                    voice.synthesize_wav(text, wav)
            else:                                          # piper-tts 1.2
                voice.synthesize(text, wav, length_scale=LENGTH_SCALE)
        buf.seek(0)
        with wave.open(buf, "rb") as wav:
            rate = wav.getframerate()
            channels = wav.getnchannels()
            frames = wav.readframes(wav.getnframes())
        if channels != 1:
            import numpy as np

            frames = (
                np.frombuffer(frames, dtype=np.int16)
                .reshape(-1, channels).mean(axis=1).astype(np.int16).tobytes()
            )
        return resample_pcm16(frames, rate, PLAY_RATE)


# ----------------------------------------------------------------------
# G1 voice service client (PlayStream rebuilt for the old SDK)
# ----------------------------------------------------------------------

def make_voice_client():
    from unitree_sdk2py.rpc.client import Client

    class G1VoiceClient(Client):
        def __init__(self):
            super().__init__(AUDIO_SERVICE_NAME, False)
            self._tts_index = 0

        def Init(self):
            self._SetApiVerson(AUDIO_API_VERSION)
            for api in (API_TTS, API_START_PLAY, API_STOP_PLAY,
                        API_GET_VOLUME, API_SET_VOLUME):
                self._RegistApi(api, 0)

        def tts_maker(self, text: str, speaker_id: int = 1) -> int:
            self._tts_index += 1
            param = json.dumps({"index": self._tts_index, "text": text,
                                "speaker_id": speaker_id})
            code, _ = self._Call(API_TTS, param)
            return code

        def play_stream(self, app_name: str, stream_id: str, pcm: bytes) -> int:
            param = json.dumps({"app_name": app_name, "stream_id": stream_id})
            binary = list(pcm)
            # Newer SDKs have this helper; use it when present.
            if hasattr(self, "_CallRequestWithParamAndBin"):
                code, _ = self._CallRequestWithParamAndBin(API_START_PLAY, param, binary)
                return code
            return self._param_and_bin(API_START_PLAY, param, binary)

        def play_stop(self, app_name: str) -> int:
            code, _ = self._Call(API_STOP_PLAY, json.dumps({"app_name": app_name}))
            return code

        def _param_and_bin(self, api_id: int, param: str, binary: list) -> int:
            # Same as the official ClientBase._CallRequestWithParamAndBinBase:
            # one Request carrying BOTH the JSON parameter and the binary.
            from unitree_sdk2py.idl.unitree_api.msg.dds_ import Request_ as Request
            from unitree_sdk2py.rpc import internal
            from unitree_sdk2py.utils.future import FutureResult

            stub = self._ClientBase__stub
            timeout = self._ClientBase__timeout
            header = self._ClientBase__SetHeader(api_id, 0, 0, False)
            request = Request(header, param, binary)

            future = stub.SendRequest(request, timeout)
            if future is None:
                return internal.RPC_ERR_CLIENT_SEND
            result = future.GetResult(timeout)
            if result.code != FutureResult.FUTURE_SUCC:
                stub.RemoveFuture(request.header.identity.id)
                return (internal.RPC_ERR_CLIENT_API_TIMEOUT
                        if result.code == FutureResult.FUTUTE_ERR_TIMEOUT
                        else internal.RPC_ERR_UNKNOWN)
            response = result.value
            if response.header.identity.api_id != api_id:
                return internal.RPC_ERR_CLIENT_API_NOT_MATCH
            return response.header.status.code

    client = G1VoiceClient()
    client.SetTimeout(10.0)
    client.Init()
    return client


# ----------------------------------------------------------------------
# Speaker: queue + playback thread
# ----------------------------------------------------------------------

class Speaker:
    def __init__(self, client, tts: PiperTTS, sleep=time.sleep, clock=time.monotonic):
        self.client = client
        self.tts = tts
        self.sleep = sleep
        self.clock = clock
        self._queue: "queue.Queue[tuple[str, bytes, float]]" = queue.Queue()
        self._lock = threading.Lock()
        self._busy_until = 0.0
        self._stop_gen = 0
        self.last_error = ""

    # -- public ---------------------------------------------------------

    def speaking(self) -> bool:
        with self._lock:
            return self.clock() < self._busy_until or not self._queue.empty()

    def remaining_ms(self) -> int:
        with self._lock:
            return max(0, int((self._busy_until - self.clock()) * 1000))

    def speak(self, text: str, lang: str | None, allow_queue: bool) -> dict:
        lang = lang if lang in ("de", "en") else detect_language(text)

        if self.speaking() and not allow_queue:
            return {"status": 409, "error": "Robot is already speaking"}
        if self._queue.qsize() >= MAX_QUEUE:
            return {"status": 429, "error": "Speech queue is full"}

        if self.tts.available(lang):
            pcm = self.tts.synthesize(text, lang)
            duration = pcm_duration(pcm)
            stream_id = f"{APP_NAME}-{int(time.time() * 1000)}"
            with self._lock:
                start = max(self.clock(), self._busy_until)
                self._busy_until = start + duration + END_MARGIN
                end_at = self._busy_until
                ends_in = end_at - self.clock()
            self._queue.put((stream_id, pcm, end_at))
            return {"status": 200, "accepted": True, "engine": "piper",
                    "lang": lang, "duration_ms": int(duration * 1000),
                    "ends_in_ms": int(ends_in * 1000), "code": 0}

        # Fallback: built-in Unitree TTS (English voice, no German).
        code = self.client.tts_maker(text, 1)
        if code != 0:
            return {"status": 502, "error": "Unitree TTS failed", "code": code}
        estimate = max(1.0, len(text.split()) / 2.6)
        with self._lock:
            self._busy_until = self.clock() + estimate
        return {"status": 200, "accepted": True, "engine": "unitree_tts",
                "lang": lang, "duration_ms": int(estimate * 1000),
                "ends_in_ms": int(estimate * 1000), "code": 0}

    def stop(self) -> None:
        with self._lock:
            self._stop_gen += 1
            self._busy_until = 0.0
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        try:
            self.client.play_stop(APP_NAME)
        except Exception as exc:
            self.last_error = f"stop: {exc}"

    # -- playback thread -----------------------------------------------

    def run_forever(self) -> None:
        while True:
            stream_id, pcm, end_at = self._queue.get()
            self.play(stream_id, pcm, end_at)

    def play(self, stream_id: str, pcm: bytes, end_at: float) -> None:
        gen = self._stop_gen
        offset = 0
        while offset < len(pcm):
            if gen != self._stop_gen:
                return
            chunk = pcm[offset:offset + CHUNK_BYTES]
            try:
                code = self.client.play_stream(APP_NAME, stream_id, chunk)
                if code != 0:
                    self.last_error = f"PlayStream returned {code}"
                    print(f"[G1 Voice] {self.last_error}", flush=True)
                    return
            except Exception as exc:
                self.last_error = f"PlayStream failed: {exc}"
                print(f"[G1 Voice] {self.last_error}", flush=True)
                return
            offset += len(chunk)
            if offset < len(pcm):
                self.sleep(CHUNK_PAUSE)
        # Wait until this sentence has been heard before sending the next,
        # so two streams never overlap on the robot speaker.
        while gen == self._stop_gen:
            left = end_at - END_MARGIN - self.clock()
            if left <= 0:
                return
            self.sleep(min(0.1, left))


# ----------------------------------------------------------------------
# HTTP server
# ----------------------------------------------------------------------

speaker: Speaker | None = None


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            tts = speaker.tts if speaker else None
            self.send_json(200, {
                "status": "ready",
                "service": "g1-speech",
                "interface": INTERFACE,
                "engine": "piper" if tts and tts.voices else "unitree_tts",
                "voices": sorted(tts.voices) if tts else [],
                "voice_errors": tts.errors if tts else {},
            })
        elif self.path == "/status":
            self.send_json(200, {
                "speaking": speaker.speaking() if speaker else False,
                "remaining_ms": speaker.remaining_ms() if speaker else 0,
                "queued": speaker._queue.qsize() if speaker else 0,
                "last_error": speaker.last_error if speaker else "",
            })
        else:
            self.send_json(404, {"error": "Not found"})

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid content length"})
            return None
        if not 0 <= length <= 4096:
            self.send_json(400, {"error": "Invalid request size"})
            return None
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "Invalid JSON"})
            return None
        if not isinstance(data, dict):
            self.send_json(400, {"error": "Expected JSON object"})
            return None
        return data

    def do_POST(self) -> None:
        if self.path == "/stop":
            if speaker:
                speaker.stop()
            self.send_json(200, {"stopped": True})
            return
        if self.path != "/speak":
            self.send_json(404, {"error": "Not found"})
            return

        request = self._read_json()
        if request is None:
            return
        text = request.get("text")
        if not isinstance(text, str):
            self.send_json(400, {"error": "Text must be a string"})
            return
        text = text.strip()
        if not text or len(text) > MAX_TEXT_LENGTH:
            self.send_json(400, {"error": "Invalid text length"})
            return
        if speaker is None:
            self.send_json(503, {"error": "Audio unavailable"})
            return

        try:
            result = speaker.speak(
                text, request.get("lang"), bool(request.get("queue", False))
            )
        except Exception as error:
            print(f"[G1 Voice] {error}", flush=True)
            self.send_json(502, {"error": "Robot speech request failed"})
            return
        status = result.pop("status")
        self.send_json(status, result)

    def log_message(self, format_string, *args) -> None:
        return


def main() -> None:
    global speaker
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize

    ChannelFactoryInitialize(0, INTERFACE)
    client = make_voice_client()
    tts = PiperTTS()
    speaker = Speaker(client, tts)
    threading.Thread(target=speaker.run_forever, name="g1-voice-play",
                     daemon=True).start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    engine = "Piper " + "+".join(sorted(tts.voices)) if tts.voices else "Unitree TTS (fallback)"
    print(f"[G1 Voice] Ready at http://{HOST}:{PORT}  voice: {engine}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        speaker.stop()
        server.server_close()


if __name__ == "__main__":
    main()
