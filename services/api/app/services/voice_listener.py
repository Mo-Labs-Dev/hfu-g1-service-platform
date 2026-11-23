"""
"Hey G1" - talk to the robot directly (G1's own head microphone), always on with G1 Studio.

  G1 microphone (UDP multicast 239.168.123.161:5555, 16 kHz mono; needs "Wake-up Conversation
  Mode" in the Unitree app) -> energy VAD cuts utterances -> local Whisper (faster-whisper,
  English + German) -> "hey g1 ..." ? -> the same skills as the app:
      spoken task ("show me target A")  -> task runner (look / walk / arm)
      guide       ("take me to the coffee machine") -> robot guide
      vision      ("what do you see?") -> G1 Vision
      otherwise   -> local chat AI, spoken by G1
  Every heard command and reply is broadcast to the apps (WebSocket type "voice"), so a
  conversation by voice also appears in Talk to G1 on the tablet.

The microphone is ignored while G1 speaks its own reply (no talking to itself), and nothing
happens without the wake word ("Hey G1" / "Hallo G1"). Disable: G1_VOICE_LISTENER=0.
"""
from __future__ import annotations

import math
import os
import re
import socket
import struct
import threading
import time
from collections import deque

import numpy as np

RATE = 16000
FRAME = 480                         # 30 ms
GROUP, PORT = "239.168.123.161", 5555


# ------------------------------------------------------------------ voice activity (pure, tested)
class Segmenter:
    """Cuts speech out of a continuous 16 kHz stream with an adaptive noise floor."""

    def __init__(self, start_db: float = 10.0, stop_db: float = 6.0, start_frames: int = 4,
                 end_frames: int = 25, preroll_frames: int = 10, max_s: float = 10.0, min_s: float = 0.4):
        self.start_db, self.stop_db = start_db, stop_db
        self.start_frames, self.end_frames = start_frames, end_frames
        self.max_frames, self.min_frames = int(max_s * RATE / FRAME), int(min_s * RATE / FRAME)
        self.floor = -50.0
        self.pre = deque(maxlen=preroll_frames)
        self.loud = 0
        self.quiet = 0
        self.active: list | None = None

    @staticmethod
    def level(frame: np.ndarray) -> float:
        rms = math.sqrt(float(np.mean(frame.astype(np.float64) ** 2))) if len(frame) else 0.0
        return 20 * math.log10(max(rms, 1.0) / 32768)

    def feed(self, frame: np.ndarray):
        """One 30 ms frame -> a finished utterance (np.int16) or None."""
        db = self.level(frame)
        if self.active is None:
            if db < self.floor + self.start_db:            # learn the room only while nobody talks
                # (never below -60 dB: digital silence between packets must not make it hyper-sensitive)
                self.floor = max(-60.0, 0.95 * self.floor + 0.05 * db)
            self.pre.append(frame)
            self.loud = self.loud + 1 if db > self.floor + self.start_db else 0
            if self.loud >= self.start_frames:
                self.active = list(self.pre)
                self.quiet = 0
            return None
        self.active.append(frame)
        self.quiet = self.quiet + 1 if db < self.floor + self.stop_db else 0
        if self.quiet >= self.end_frames or len(self.active) >= self.max_frames:
            seg, self.active = self.active, None
            self.loud = 0
            self.pre.clear()
            speech = len(seg) - self.quiet
            return np.concatenate(seg) if speech >= self.min_frames else None
        return None


# ------------------------------------------------------------------ wake word (pure, tested)
GREETINGS = {"hey", "hi", "hallo", "hello", "ok", "okay", "hej", "he", "ey", "hei", "ay", "a", "yeah", "hay", "high"}
_G1_WORD = re.compile(r"^(g|j|ch|dj|dsch|sch)(ee|ie|i|e|y)?(1|one|won|wan|wun|eins|ein|wonn)$")


def normalise(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"\bg\s*-?\s*1\b", "g1", t)
    t = re.sub(r"[^a-zäöüß0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def split_wake(text: str) -> tuple[bool, str]:
    """('Hey G1, show me target A') -> (True, 'show me target a'). Whisper writes the name in many
    ways ('G1', 'G-1', 'Gee one', 'Jiwan', 'G one'), so the name is matched loosely - but only
    right after a greeting at the start of the sentence."""
    w = normalise(text).split()
    for start in range(0, min(2, len(w))):
        if w[start] not in GREETINGS:
            continue
        rest = w[start + 1:]
        for n in (1, 2, 3):                     # the name may be split into up to 3 words
            if len(rest) >= n and _G1_WORD.match("".join(rest[:n])):
                return True, " ".join(rest[n:]).strip()
        return False, ""
    return False, ""


# short on purpose: a long prompt is sometimes "heard" back by Whisper on silence
PROMPT = "The robot is called G1. Hey G1, Hallo G1."


def is_hallucination(text: str) -> bool:
    """Typical Whisper inventions on noise: the prompt itself, or a phrase repeated over and over."""
    t = normalise(text)
    if not t:
        return True
    if t in {"hfu lab yaskawa robot", "thank you for watching", "thanks for watching",
             "untertitel im auftrag des zdf", "you", "the robot is called g1"}:
        return True
    words = t.split()
    for n in (1, 2, 3):
        grams = [" ".join(words[i:i + n]) for i in range(0, len(words) - n + 1)]
        if grams and max(grams.count(g) for g in set(grams)) >= 4:
            return True
    return False


# ------------------------------------------------------------------ the listener
class VoiceListener:
    """Natural conversation with G1's own microphone:
       "Hey G1" (+ question) starts a conversation; after each answer G1 keeps listening for
       `conversation_s` seconds WITHOUT the wake word (like talking to a person). "Thank you" /
       "bye" ends it. G1's own voice is never taken as input: utterances recorded while G1 was
       speaking are dropped (by recording time, not by processing time)."""

    BYE = re.compile(r"\b(bye|goodbye|thank you|thanks|that s all|stop listening|tschüss|tschuess|"
                     r"auf wiedersehen|danke|das wars|das war s)\b")

    def __init__(self, transcribe, dispatch, say, broadcast=None, clock=time.monotonic,
                 follow_up_s: float = 7.0, conversation_s: float = 12.0):
        self.transcribe, self.dispatch, self.say = transcribe, dispatch, say
        self.broadcast = broadcast or (lambda ev: None)
        self.clock = clock
        self.follow_up_s = follow_up_s
        self.conversation_s = conversation_s
        self.speaking: list[list[float]] = []          # [start, end] when G1's speaker is busy
        self.talk_until = 0.0                          # conversation window (no wake word needed)
        self.seg = Segmenter(end_frames=20)
        self.queue = None
        self.lang_hint = None
        self.state = {"enabled": True, "mic": "waiting", "packets": 0, "last_heard": None,
                      "last_command": None, "last_reply": None, "errors": 0, "conversation": False,
                      "echo_dropped": 0}
        self.recent_replies: list[tuple[float, str]] = []   # what G1 said itself (echo filter)
        self.free_turns = 0                                   # turns without wake word in this talk
        self.MAX_FREE_TURNS = 4

    # ---------------------------------------------------------------- G1's own voice
    @property
    def mute_until(self) -> float:
        return max((e for _, e in self.speaking), default=0.0)

    def mute_for(self, seconds: float) -> None:
        now = self.clock()
        self.speaking = [iv for iv in self.speaking if iv[1] > now - 60] + [[now, now + max(0.0, seconds)]]

    def _was_speaking(self, t0: float, t1: float) -> bool:
        dur = max(t1 - t0, 1e-3)
        overlap = sum(max(0.0, min(t1, e) - max(t0, s)) for s, e in self.speaking)
        return overlap / dur > 0.4

    @staticmethod
    def speech_seconds(text: str) -> float:
        """How long G1 needs to say `text` (when the voice bridge does not tell us)."""
        return 0.075 * len(text or "") + 1.0

    def remember_reply(self, text: str) -> None:
        now = self.clock()
        self.recent_replies = [(t, r) for t, r in self.recent_replies if now - t < 90] + [(now, normalise(text))]

    def is_echo(self, text: str) -> bool:
        """Did G1 just hear (part of) its own sentence? Word overlap with a recent reply."""
        words = set(normalise(text).split())
        if len(words) < 4:                       # short questions are never treated as echo
            return False
        for _, r in self.recent_replies:
            common = words & set(r.split())
            if len(common) >= 4 and len(common) / len(words) >= 0.7:
                return True
        return False

    def _open_conversation(self, seconds: float | None = None) -> None:
        self.talk_until = max(self.mute_until, self.clock()) + (seconds or self.conversation_s)
        self.state["conversation"] = True

    # ---------------------------------------------------------------- audio in
    def on_audio(self, pcm: np.ndarray) -> None:
        """Feed raw microphone samples (any length). Utterances go to worker() when a queue is
        attached (the microphone thread never waits for speech recognition)."""
        self.state["packets"] += 1
        self.state["mic"] = "ok"
        self._buf = np.concatenate([getattr(self, "_buf", np.zeros(0, np.int16)), pcm])
        while len(self._buf) >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            utt = self.seg.feed(frame)
            if utt is not None:
                t_end = self.clock()
                if self.queue is None:
                    self.on_utterance(utt, t_end)
                elif self.queue.qsize() < 4:
                    self.queue.put((utt, t_end))

    def worker(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            self.on_utterance(*item)

    # ---------------------------------------------------------------- one utterance
    def on_utterance(self, audio: np.ndarray, t_end: float | None = None) -> None:
        t_end = self.clock() if t_end is None else t_end
        t_start = t_end - len(audio) / RATE
        if not self.state["enabled"] or self._was_speaking(t_start, t_end):
            return                                       # G1 heard itself
        t0 = time.monotonic()
        try:
            text, lang = self.transcribe(audio)
        except Exception:
            self.state["errors"] += 1
            return
        self.state["last_transcribe_s"] = round(time.monotonic() - t0, 2)
        text = (text or "").strip()
        if not text:
            return
        self.state["last_heard"] = text
        self.state["recent"] = (self.state.get("recent", []) + [text])[-6:]
        if self.is_echo(text):
            self.state["echo_dropped"] += 1           # G1 heard itself -> never answer that
            return
        woke, command = split_wake(text)
        if woke:
            self.free_turns = 0
        in_talk = t_end < self.talk_until
        if not woke and in_talk:
            if self.free_turns >= self.MAX_FREE_TURNS:  # safety net: no endless talking
                self.talk_until = 0.0
                self.state["conversation"] = False
                return
            self.free_turns += 1
            woke, command = True, normalise(text)
        if not woke:
            if self.clock() > self.talk_until:
                self.state["conversation"] = False
            return
        if len(command.split()) < 2:
            if command and self.BYE.search(command):
                pass                                     # "Hey G1, thanks" -> handled below
            else:
                queued = self.queue is not None and not self.queue.empty()
                if not queued:                           # the visitor is not already talking on
                    self.say("Ja?" if lang == "de" else "Yes?", lang)
                    self.mute_for(1.2)
                self._open_conversation(self.follow_up_s)
                self.broadcast({"type": "voice", "data": {"heard": text, "reply": None, "lang": lang,
                                                          "waiting": True}})
                return
        if self.BYE.search(command) and len(command.split()) <= 4:
            reply = "Gern geschehen. Bis bald!" if lang == "de" else "You're welcome. Talk to you later!"
            self.remember_reply(reply)
            self.say(reply, lang)
            self.mute_for(self.speech_seconds(reply))
            self.talk_until = 0.0
            self.state["conversation"] = False
            self.broadcast({"type": "voice", "data": {"heard": text, "command": command, "reply": reply, "lang": lang}})
            return
        self.state["last_command"] = command
        self.state["last_wait_to_answer_s"] = round(self.clock() - t_end, 2)
        try:
            reply, speak_s = self.dispatch(command, lang)
        except Exception as exc:
            self.state["errors"] += 1
            reply, speak_s = (f"Entschuldigung, das ging nicht: {exc}" if lang == "de"
                              else f"Sorry, that did not work: {exc}"), 0.0
            self.say(reply, lang)
        self.state["last_reply"] = reply
        self.remember_reply(reply)
        # until G1 has finished speaking it does not listen (bridge time, else estimated from the text)
        self.mute_for(max(speak_s or 0.0, self.speech_seconds(reply)) + 0.5)
        self._open_conversation()
        self.broadcast({"type": "voice", "data": {"heard": text, "command": command, "reply": reply, "lang": lang,
                                                  "seconds": round(self.clock() - t_end, 2)}})


# ------------------------------------------------------------------ wiring to G1 Studio
def _robot_ip() -> str | None:
    try:
        import subprocess
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True).stdout
        m = re.search(r"inet (192\.168\.123\.\d+)/", out)
        return m.group(1) if m else None
    except Exception:
        return None


def _mic_thread(listener: VoiceListener, stop: threading.Event) -> None:
    while not stop.is_set():
        ip = os.getenv("G1_MIC_IFACE_IP") or _robot_ip()
        if not ip:
            listener.state["mic"] = "no robot network (192.168.123.x)"
            time.sleep(10)
            continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", PORT))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GROUP) + socket.inet_aton(ip))
            s.settimeout(2.0)
            last = time.monotonic()
            while not stop.is_set():
                try:
                    data, _ = s.recvfrom(65536)
                except socket.timeout:
                    if time.monotonic() - last > 5:
                        listener.state["mic"] = ("no microphone audio - set 'Wake-up Conversation Mode' "
                                                 "in the Unitree app")
                    continue
                last = time.monotonic()
                n = len(data) // 2
                if n:
                    listener.on_audio(np.frombuffer(data[: n * 2], dtype="<i2"))
        except Exception as exc:
            listener.state["mic"] = f"error: {exc}"
            time.sleep(5)


_listener: VoiceListener | None = None


def get() -> VoiceListener | None:
    return _listener


def start(loop) -> VoiceListener | None:
    """Called from the app lifespan. Returns None when disabled."""
    global _listener
    if os.getenv("G1_VOICE_LISTENER", "1") == "0":
        return None
    import asyncio

    from app.api.task import runner as task_runner
    from app.api.websocket import manager
    from app.services import robot_hub
    from app.services.interaction_service import interaction_service

    model_holder = {}

    def _load():
        """GPU if this machine's CTranslate2 has CUDA (more accurate model, ~1 s), else CPU with
        all fast cores (base model)."""
        from faster_whisper import WhisperModel
        try:
            import ctranslate2
            cuda = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            cuda = False
        if cuda:
            name = os.getenv("G1_WAKE_MODEL", "small")
            model_holder["m"] = WhisperModel(name, device="cuda", compute_type="float16")
            model_holder["desc"] = f"{name}, GPU"
        else:
            name = os.getenv("G1_WAKE_MODEL", "base")
            threads = int(os.getenv("G1_WAKE_THREADS", str(min(8, os.cpu_count() or 4))))
            model_holder["m"] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
            model_holder["desc"] = f"{name}, CPU x{threads}"

    def transcribe(audio: np.ndarray):
        if "m" not in model_holder:
            _load()
        # during a conversation the language is known -> skip language detection (faster)
        hint = _listener.lang_hint if (_listener is not None and _listener.clock() < _listener.talk_until) else None
        kw = dict(beam_size=1, condition_on_previous_text=False, vad_filter=False, without_timestamps=True,
                  language=hint, initial_prompt=PROMPT)
        try:
            segs, info = model_holder["m"].transcribe(audio.astype(np.float32) / 32768.0, hotwords="G1", **kw)
        except TypeError:                         # older faster-whisper without hotwords
            segs, info = model_holder["m"].transcribe(audio.astype(np.float32) / 32768.0, **kw)
        # drop what Whisper invents on noise / silence (low confidence, "no speech")
        segs = [sg for sg in segs if not (getattr(sg, "no_speech_prob", 0) > 0.6 and getattr(sg, "avg_logprob", 0) < -0.7)
                and getattr(sg, "avg_logprob", 0) > -1.2]
        text = " ".join(sg.text.strip() for sg in segs).strip()
        if is_hallucination(text):
            text = ""
        lang = "de" if getattr(info, "language", "en") == "de" else "en"
        if _listener is not None and text:
            _listener.lang_hint = lang
        return text, lang

    def say(text, lang):
        _listener.remember_reply(text)
        try:
            code, body = robot_hub.post_json(f"{robot_hub.VOICE}/speak", {"text": text, "lang": lang}, timeout=5)
            ms = (body or {}).get("ends_in_ms")
            _listener.mute_for(ms / 1000.0 if isinstance(ms, int) else 0.08 * len(text) + 0.8)
        except Exception:
            pass

    session = {"id": None}
    guide_words = ("take me", "bring me", "guide me", "lead me", "show me the way", "where is", "way to",
                   "tour", "führ", "bring mich", "zeig mir den weg", "wo ist", "rundgang", "führung")
    look_words = ("what do you see", "what can you see", "what is this", "was siehst du", "was ist das")

    def dispatch(command: str, lang: str):
        de = lang == "de"
        out = task_runner.handle(command, lang)
        if out.get("handled"):
            say(out["reply"], lang)
            return out["reply"], 0.0
        if any(w in command for w in guide_words):
            try:
                routes = robot_hub.routes()
                routes = routes.get("routes", routes) if isinstance(routes, dict) else routes
            except Exception:
                routes = []
            for r in routes or []:
                titles = {str(r.get(k, "")).lower() for k in ("title_en", "title_de", "name")} - {""}
                titles |= {t.replace("_", " ") for t in titles}
                if any(t and t in command for t in titles) or (("tour" in command or "rundgang" in command)
                                                              and r.get("kind") == "tour"):
                    code, data = robot_hub.guide_start(r["name"], lang)
                    title = r.get("title_de" if de else "title_en") or r["name"]
                    if code < 400:
                        return (f"Bitte folgen Sie mir: {title}." if de else f"Please follow me: {title}."), 0.0
                    reply = (f"Ich kann gerade nicht führen: {(data or {}).get('detail', '')}" if de
                             else f"I can't guide right now: {(data or {}).get('detail', '')}")
                    say(reply, lang)
                    return reply, 0.0
        if any(w in command for w in look_words):
            code, data = robot_hub.vision_describe(command, lang)
            if code < 400:
                return (data or {}).get("answer", ""), 6.0
        fut = asyncio.run_coroutine_threadsafe(
            interaction_service.ask(question=command, speak=True, session_id=session["id"], language=lang,
                                 source="mic"), loop)
        res = fut.result(timeout=90)
        res = res if isinstance(res, dict) else res.__dict__
        session["id"] = res.get("session_id", session["id"])
        ends = res.get("speech_ends_in_ms")
        return res.get("answer", ""), (ends / 1000.0 if isinstance(ends, int) else 0.0)

    def broadcast(ev):
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast(ev), loop)
        except Exception:
            pass
        d = ev.get("data") or {}
        if ev.get("type") == "voice" and d.get("reply"):          # Studio Interaction page log
            try:
                from app.services import interaction_control
                interaction_control.record("mic", d.get("heard", ""), d["reply"], d.get("lang", "en"),
                                           d.get("seconds"), spoke=True)
            except Exception:
                pass

    _listener = VoiceListener(transcribe, dispatch, say, broadcast)
    import queue as _q
    _listener.queue = _q.Queue()
    stop = threading.Event()
    _listener._stop = stop

    def preload():
        _listener.state["model"] = "loading..."
        try:
            transcribe(np.zeros(RATE // 2, np.int16))
            _listener.state["model"] = f"ready ({model_holder.get('desc')})"
        except Exception as exc:
            _listener.state["model"] = f"error: {exc}"
    threading.Thread(target=preload, daemon=True, name="g1-whisper-load").start()
    threading.Thread(target=_listener.worker, daemon=True, name="g1-voice").start()
    threading.Thread(target=_mic_thread, args=(_listener, stop), daemon=True, name="g1-mic").start()
    return _listener


def stop() -> None:
    if _listener is not None and getattr(_listener, "_stop", None):
        _listener._stop.set()
