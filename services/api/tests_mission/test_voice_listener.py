import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.voice_listener import FRAME, RATE, Segmenter, VoiceListener, split_wake  # noqa: E402


def noise(seconds, amp=200, seed=0):
    return (np.random.default_rng(seed).normal(0, amp, int(seconds * RATE))).astype(np.int16)


def speech(seconds, amp=6000, seed=1):
    t = np.arange(int(seconds * RATE)) / RATE
    rng = np.random.default_rng(seed)
    return (amp * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * rng.random(len(t)))).astype(np.int16)


def feed_all(seg, pcm):
    out = []
    for k in range(0, len(pcm) - FRAME + 1, FRAME):
        u = seg.feed(pcm[k:k + FRAME])
        if u is not None:
            out.append(u)
    return out


def test_segmenter_cuts_one_utterance_from_noise():
    pcm = np.concatenate([noise(2.0), speech(1.5), noise(1.5, seed=3)])
    utts = feed_all(Segmenter(), pcm)
    assert len(utts) == 1
    assert 1.4 < len(utts[0]) / RATE < 2.6


def test_segmenter_ignores_short_clicks_and_noise():
    pcm = np.concatenate([noise(2.0), speech(0.15), noise(2.0, seed=4)])
    assert feed_all(Segmenter(), pcm) == []


def test_wake_word_variants():
    assert split_wake("Hey G1, show me target A.") == (True, "show me target a")
    assert split_wake("hey g one what do you see") == (True, "what do you see")
    assert split_wake("Hallo G-1 zeig mir Ziel B") == (True, "zeig mir ziel b")
    assert split_wake("Hey, G1!")[0] is True
    assert split_wake("Let me look for target A.") == (False, "")
    assert split_wake("This is target A") == (False, "")


class Fake:
    def __init__(self, texts):
        self.texts = list(texts)
        self.said, self.cmds, self.events = [], [], []
        self.t = 0.0

    def transcribe(self, audio):
        return self.texts.pop(0), "en"

    def dispatch(self, cmd, lang):
        self.cmds.append(cmd)
        return f"ok: {cmd}", 2.0

    def say(self, text, lang):
        self.said.append(text)


def test_listener_wake_then_command_and_mute():
    f = Fake(["hey g1 show me target a", "hey g1 what do you see"])
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, f.events.append, clock=lambda: f.t)
    lst.on_utterance(np.zeros(8000, np.int16))
    assert f.cmds == ["show me target a"] and f.events[-1]["data"]["reply"] == "ok: show me target a"
    f.t = 1.0                                   # recorded while G1 was answering -> its own voice
    lst.on_utterance(np.zeros(8000, np.int16))
    assert len(f.cmds) == 1
    f.t = 5.0
    lst.on_utterance(np.zeros(8000, np.int16))
    assert f.cmds[-1] == "what do you see"


def test_listener_wake_alone_asks_then_takes_next_sentence():
    f = Fake(["Hey G1.", "show me the object", "show me the object"])
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, clock=lambda: f.t)
    lst.on_utterance(np.zeros(8000, np.int16))
    assert f.said == ["Yes?"] and f.cmds == []
    f.t = 3.0
    lst.on_utterance(np.zeros(8000, np.int16))
    assert f.cmds == ["show me the object"]
    f.t = 30.0                                  # no wake word, window over -> ignored
    lst.on_utterance(np.zeros(8000, np.int16))
    assert len(f.cmds) == 1


def test_ignores_everything_without_wake_word():
    f = Fake(["there it is this is target a", "please let me pass"])
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, clock=lambda: f.t)
    lst.on_utterance(np.zeros(8000, np.int16))
    lst.on_utterance(np.zeros(8000, np.int16))
    assert f.cmds == [] and f.said == []


def test_conversation_continues_without_wake_word_then_ends():
    f = Fake(["hey g1 what is this lab about", "and who works here", "thank you", "what time is it"])
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, clock=lambda: f.t)
    lst.on_utterance(np.zeros(8000, np.int16))           # wake + question
    f.t = 6.0                                            # follow-up, no "Hey G1" needed
    lst.on_utterance(np.zeros(8000, np.int16))
    assert f.cmds == ["what is this lab about", "and who works here"]
    f.t = 12.0
    lst.on_utterance(np.zeros(8000, np.int16))           # "thank you" ends the conversation
    assert "You're welcome" in f.said[-1]
    f.t = 16.0
    lst.on_utterance(np.zeros(8000, np.int16))           # no wake word any more -> ignored
    assert len(f.cmds) == 2


def test_command_said_before_yes_is_not_lost():
    """Visitor says "Hey G1" ... "show me target A" quickly; recognition is slow, so G1 says
    "Yes?" only after the second sentence was already recorded. It must still be the command."""
    f = Fake(["Hey G1.", "show me target a"])
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, clock=lambda: f.t)
    f.t = 3.0                                            # processed late
    lst.on_utterance(np.zeros(8000, np.int16), t_end=0.6)
    lst.on_utterance(np.zeros(16000, np.int16), t_end=2.2)   # recorded 1.2-2.2 s, before "Yes?" at 3.0
    assert f.cmds == ["show me target a"]


def test_g1_never_answers_its_own_voice():
    """The loop seen on the robot: G1 heard the end of its own answer and replied to it."""
    f = Fake(["hey g1 where is the data",
              "I don't have access to any data right now",       # G1's own reply, heard back
              "I don't have access to any data right now"])
    f.dispatch = lambda cmd, lang: (f.cmds.append(cmd) or "I don't have access to any data right now. "
                                    "I'm here to help with questions about the lab.", 0.0)
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, clock=lambda: f.t)
    lst.on_utterance(np.zeros(8000, np.int16))
    assert lst.mute_until > 5.0                     # muted for the whole (estimated) reply
    f.t = 4.0
    lst.on_utterance(np.zeros(8000, np.int16), t_end=4.0)   # inside G1's speech -> dropped
    f.t = 12.0
    lst.on_utterance(np.zeros(8000, np.int16), t_end=12.0)  # after it, but it is an echo -> dropped
    assert len(f.cmds) == 1 and lst.state["echo_dropped"] == 1


def test_free_turns_are_limited():
    f = Fake(["hey g1 hello there"] + [f"question number {i} please" for i in range(8)])
    f.dispatch = lambda cmd, lang: (f.cmds.append(cmd) or "Sure, here is my answer for you.", 0.0)
    lst = VoiceListener(f.transcribe, f.dispatch, f.say, clock=lambda: f.t)
    lst.on_utterance(np.zeros(8000, np.int16))
    for i in range(8):
        f.t += 5.0
        lst.on_utterance(np.zeros(8000, np.int16), t_end=f.t)
    assert len(f.cmds) == 1 + lst.MAX_FREE_TURNS


def test_hallucination_filter():
    from app.services.voice_listener import is_hallucination
    assert is_hallucination("HFU lab, Yaskawa robot.")
    assert is_hallucination("The battery is low. 20,000. 20,000. 20,000. 20,000.")
    assert not is_hallucination("Hey G1, what is this lab about?")
    assert not is_hallucination("Hallo G1.")
