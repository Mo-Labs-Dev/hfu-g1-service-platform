"""Tests for g1_voice_bridge with a faithful fake of the user's OLD unitree SDK."""
import io, json, sys, threading, time, types, wave, urllib.request, urllib.error
from pathlib import Path
import numpy as np
import pytest

SENT = []  # requests seen by the fake robot

# ---- fake unitree_sdk2py (old ClientBase copied from the user's install) ----
def install_fake_sdk(status_code=0):
    mods = {}
    for n in ["unitree_sdk2py", "unitree_sdk2py.rpc", "unitree_sdk2py.idl",
              "unitree_sdk2py.idl.unitree_api", "unitree_sdk2py.idl.unitree_api.msg",
              "unitree_sdk2py.utils", "unitree_sdk2py.core"]:
        mods[n] = types.ModuleType(n)

    dds = types.ModuleType("unitree_sdk2py.idl.unitree_api.msg.dds_")
    class Request_:
        def __init__(self, header, parameter, binary):
            self.header, self.parameter, self.binary = header, parameter, binary
    class RequestHeader_:
        def __init__(self, identity, lease, policy): self.identity, self.lease, self.policy = identity, lease, policy
    class RequestIdentity_:
        def __init__(self, id, api_id): self.id, self.api_id = id, api_id
    class RequestLease_:
        def __init__(self, id): self.id = id
    class RequestPolicy_:
        def __init__(self, priority, noreply): self.priority, self.noreply = priority, noreply
    for c in (Request_, RequestHeader_, RequestIdentity_, RequestLease_, RequestPolicy_):
        setattr(dds, c.__name__, c)

    fut = types.ModuleType("unitree_sdk2py.utils.future")
    class FutureResult:
        FUTURE_SUCC = 0; FUTUTE_ERR_TIMEOUT = 1
        def __init__(self, code, value=None): self.code, self.value = code, value
    fut.FutureResult = FutureResult

    internal = types.ModuleType("unitree_sdk2py.rpc.internal")
    internal.RPC_ERR_CLIENT_SEND = 3102; internal.RPC_ERR_CLIENT_API_TIMEOUT = 3104
    internal.RPC_ERR_UNKNOWN = 3001; internal.RPC_ERR_CLIENT_API_NOT_MATCH = 3103
    internal.RPC_ERR_CLIENT_API_NOT_REG = 3105; internal.RPC_INTERNAL_API_ID_MAX = 100

    class Future:
        def __init__(self, req):
            self.req = req
        def GetResult(self, timeout):
            resp = types.SimpleNamespace(
                header=types.SimpleNamespace(
                    identity=types.SimpleNamespace(api_id=self.req.header.identity.api_id),
                    status=types.SimpleNamespace(code=status_code)),
                data="", binary=[])
            return FutureResult(0, resp)

    class ClientStub:
        def __init__(self, name): self.name = name
        def Init(self): pass
        def SendRequest(self, request, timeout):
            SENT.append((self.name, request)); return Future(request)
        def RemoveFuture(self, i): pass

    # ---- copy of the user's OLD client_base.ClientBase (name-mangled privates) ----
    class ClientBase:
        def __init__(self, serviceName):
            self.__timeout = 1.0
            self.__stub = ClientStub(serviceName)
            self.__stub.Init()
        def SetTimeout(self, timeout): self.__timeout = timeout
        def _CallBase(self, apiId, parameter, proirity=0, leaseId=0):
            header = self.__SetHeader(apiId, leaseId, proirity, False)
            request = Request_(header, parameter, [])
            future = self.__stub.SendRequest(request, self.__timeout)
            result = future.GetResult(self.__timeout)
            r = result.value
            return r.header.status.code, r.data
        def __SetHeader(self, apiId, leaseId, priority, noReply):
            return RequestHeader_(RequestIdentity_(time.monotonic_ns(), apiId),
                                  RequestLease_(leaseId), RequestPolicy_(priority, noReply))

    client_mod = types.ModuleType("unitree_sdk2py.rpc.client")
    class Client(ClientBase):   # old Client: NO _CallRequestWithParamAndBin
        def __init__(self, serviceName, enabaleLease=False):
            super().__init__(serviceName); self.__apiMapping = {}
        def _SetApiVerson(self, v): self.ver = v
        def _RegistApi(self, apiId, p): self.__apiMapping[apiId] = p
        def _Call(self, apiId, parameter):
            if apiId not in self.__apiMapping: return 3105, None
            return self._CallBase(apiId, parameter, 0, 0)
    client_mod.Client = Client

    chan = types.ModuleType("unitree_sdk2py.core.channel")
    chan.ChannelFactoryInitialize = lambda *a: None
    mods.update({dds.__name__: dds, fut.__name__: fut, internal.__name__: internal,
                 client_mod.__name__: client_mod, chan.__name__: chan})
    mods["unitree_sdk2py.rpc"].internal = internal
    sys.modules.update(mods)


def install_fake_piper(rate=22050, seconds_per_word=0.3, new_api=True):
    piper = types.ModuleType("piper")
    class PiperVoice:
        loaded = []
        @classmethod
        def load(cls, path):
            cls.loaded.append(path); return cls()
        def _write(self, text, wav):
            n = int(rate * seconds_per_word * len(text.split()))
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
            t = np.arange(n) / rate
            wav.writeframes((np.sin(2*np.pi*220*t)*8000).astype(np.int16).tobytes())
    if new_api:
        PiperVoice.synthesize_wav = lambda self, text, wav, syn_config=None: self._write(text, wav)
        piper.SynthesisConfig = lambda **kw: kw
    else:
        PiperVoice.synthesize = lambda self, text, wav, length_scale=1.0: self._write(text, wav)
    piper.PiperVoice = PiperVoice
    sys.modules["piper"] = piper


@pytest.fixture
def bridge(monkeypatch):
    SENT.clear()
    install_fake_sdk()
    install_fake_piper()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.modules.pop("g1_voice_bridge", None)
    import g1_voice_bridge as b
    return b


class FakeTime:
    def __init__(self): self.t = 1000.0
    def clock(self): return self.t
    def sleep(self, s): self.t += s


# ---------------------------------------------------------------- tests

def test_language_detection(bridge):
    d = bridge.detect_language
    assert d("Willkommen im Labor! Wie kann ich helfen?") == "de"
    assert d("Hallo, ich bin G1.") == "de"
    assert d("Schön, dass Sie da sind") == "de"
    assert d("Welcome to the lab, how can I help you?") == "en"
    assert d("Hello, I am G1, the humanoid robot.") == "en"


def test_resample_22050_to_16000(bridge):
    pcm = (np.zeros(22050, dtype=np.int16)).tobytes()   # 1 s
    out = bridge.resample_pcm16(pcm, 22050, 16000)
    assert abs(len(out) / 2 - 16000) <= 2


def test_play_stream_builds_param_and_binary_request(bridge):
    client = bridge.make_voice_client()
    code = client.play_stream("g1studio", "s1", b"\x01\x02\x03\x04")
    assert code == 0
    name, req = SENT[-1]
    assert name == "voice"
    assert req.header.identity.api_id == 1003
    assert json.loads(req.parameter) == {"app_name": "g1studio", "stream_id": "s1"}
    assert req.binary == [1, 2, 3, 4]                # BOTH param and binary


def test_speak_with_piper_german_and_english(bridge):
    ft = FakeTime()
    client = bridge.make_voice_client()
    tts = bridge.PiperTTS()
    assert set(tts.voices) == {"de", "en"}
    sp = bridge.Speaker(client, tts, sleep=ft.sleep, clock=ft.clock)
    r = sp.speak("Hallo, willkommen im Labor", None, False)
    assert r["status"] == 200 and r["engine"] == "piper" and r["lang"] == "de"
    assert 1100 <= r["duration_ms"] <= 1300                # 4 words * 0.3 s
    stream_id, pcm, end_at = sp._queue.get_nowait()
    sp.play(stream_id, pcm, end_at)
    plays = [q for n, q in SENT if q.header.identity.api_id == 1003]
    assert len(plays) == 1 and len(plays[0].binary) == len(pcm)
    assert ft.t >= end_at - bridge.END_MARGIN               # waited until heard


def test_long_text_is_chunked(bridge):
    ft = FakeTime()
    client = bridge.make_voice_client()
    sp = bridge.Speaker(client, bridge.PiperTTS(), sleep=ft.sleep, clock=ft.clock)
    sp.speak(" ".join(["word"] * 30), "en", False)            # 9 s audio
    sid, pcm, end_at = sp._queue.get_nowait()
    sp.play(sid, pcm, end_at)
    plays = [q for n, q in SENT if q.header.identity.api_id == 1003]
    assert len(plays) == 3                                    # 3 s chunks
    assert {json.loads(q.parameter)["stream_id"] for q in plays} == {sid}


def test_busy_returns_409_unless_queue(bridge):
    ft = FakeTime()
    sp = bridge.Speaker(bridge.make_voice_client(), bridge.PiperTTS(),
                        sleep=ft.sleep, clock=ft.clock)
    assert sp.speak("Hello there", "en", False)["status"] == 200
    assert sp.speak("Second sentence", "en", False)["status"] == 409
    r = sp.speak("Second sentence", "en", True)
    assert r["status"] == 200 and r["ends_in_ms"] > r["duration_ms"]


def test_stop_clears_queue_and_calls_playstop(bridge):
    ft = FakeTime()
    sp = bridge.Speaker(bridge.make_voice_client(), bridge.PiperTTS(),
                        sleep=ft.sleep, clock=ft.clock)
    sp.speak("one two three", "en", True)
    sp.speak("four five six", "en", True)
    sp.stop()
    assert sp._queue.empty() and not sp.speaking()
    assert any(q.header.identity.api_id == 1004 for n, q in SENT)


def test_fallback_to_unitree_tts_without_piper(bridge, monkeypatch):
    sys.modules.pop("piper")
    import builtins
    real_import = builtins.__import__
    def no_piper(name, *a, **k):
        if name == "piper": raise ImportError("no piper")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_piper)
    tts = bridge.PiperTTS()
    assert tts.voices == {} and "piper" in tts.errors
    sp = bridge.Speaker(bridge.make_voice_client(), tts)
    r = sp.speak("Hello visitors", None, False)
    assert r["engine"] == "unitree_tts"
    tts_calls = [q for n, q in SENT if q.header.identity.api_id == 1001]
    assert json.loads(tts_calls[-1].parameter)["text"] == "Hello visitors"


def test_old_piper_api_also_works(bridge):
    install_fake_piper(new_api=False)
    sp = bridge.Speaker(bridge.make_voice_client(), bridge.PiperTTS())
    assert sp.speak("Hello", "en", False)["engine"] == "piper"


def test_http_api_compatible_with_backend(bridge):
    b = bridge
    b.speaker = b.Speaker(b.make_voice_client(), b.PiperTTS())
    threading.Thread(target=b.speaker.run_forever, daemon=True).start()
    srv = b.ThreadingHTTPServer(("127.0.0.1", 0), b.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    def post(path, data):
        req = urllib.request.Request(base + path, data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
    # exactly what the existing backend sends
    code, body = post("/speak", {"text": "Hello, I am G1."})
    assert code == 200 and body["accepted"] is True
    code, body = post("/speak", {"text": "Busy?"})
    assert code == 409
    code, body = post("/speak", {"text": "Danke schön!", "queue": True})
    assert code == 200 and body["lang"] == "de"
    with urllib.request.urlopen(base + "/health") as r:
        h = json.loads(r.read())
    assert h["engine"] == "piper" and h["voices"] == ["de", "en"]
    with urllib.request.urlopen(base + "/status") as r:
        st = json.loads(r.read())
    assert st["speaking"] is True and st["remaining_ms"] > 0
    assert post("/stop", {})[0] == 200
    assert post("/speak", {"text": ""})[0] == 400
    srv.shutdown()
