"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bot,
  LoaderCircle,
  MessageSquare,
  Mic,
  MicOff,
  Send,
  Volume2,
} from "lucide-react";

type Message = {
  role: "visitor" | "g1";
  content: string;
};

type AskResponse = {
  question: string;
  answer: string;
  model: string;
  speech_accepted: boolean;
  speech_error: string | null;
};

type TranscriptionResponse = {
  text: string;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const MAX_RECORDING_MS = 15000;

export default function InteractionPage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [speak, setSpeak] = useState(false);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speechStatus, setSpeechStatus] = useState<
    string | null
  >(null);
  const [microphoneStatus, setMicrophoneStatus] = useState(
    "Microphone ready"
  );

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const busyRef = useRef(false);
  const recordingRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;

      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      const recorder = recorderRef.current;

      if (recorder) {
        recorder.onstop = null;
        recorder.ondataavailable = null;
        recorder.onerror = null;

        if (recorder.state !== "inactive") {
          recorder.stop();
        }
      }

      streamRef.current?.getTracks().forEach((track) => {
        track.stop();
      });
    };
  }, []);

  function releaseMicrophone() {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    streamRef.current?.getTracks().forEach((track) => {
      track.stop();
    });

    streamRef.current = null;
    recorderRef.current = null;
    recordingRef.current = false;

    if (mountedRef.current) {
      setRecording(false);
    }
  }

  async function askG1(textInput?: string) {
    const text = (textInput ?? question).trim();

    if (!text || busyRef.current) {
      return;
    }

    busyRef.current = true;
    setLoading(true);
    setError(null);
    setSpeechStatus(null);
    setQuestion("");

    setMessages((previous) => [
      ...previous,
      { role: "visitor", content: text },
    ]);

    try {
      const response = await fetch(
        `${API_URL}/api/interaction/ask`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            question: text,
            speak,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(
          `AI request failed (${response.status})`
        );
      }

      const result: AskResponse = await response.json();

      if (!mountedRef.current) {
        return;
      }

      setMessages((previous) => [
        ...previous,
        { role: "g1", content: result.answer },
      ]);

      if (speak) {
        setSpeechStatus(
          result.speech_accepted
            ? "Speech request accepted by physical G1"
            : `Speech unavailable: ${
                result.speech_error || "Unknown error"
              }`
        );
      }
    } catch (reason) {
      if (mountedRef.current) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to contact G1 AI"
        );
      }
    } finally {
      busyRef.current = false;

      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }

  async function transcribeAudio(
    audio: Blob,
    extension: string
  ) {
    if (!mountedRef.current) {
      return;
    }

    setTranscribing(true);
    setMicrophoneStatus("Transcribing with Whisper...");
    setError(null);

    try {
      const formData = new FormData();

      formData.append(
        "file",
        audio,
        `visitor-recording.${extension}`
      );

      const response = await fetch(
        `${API_URL}/api/interaction/transcribe`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        const details = await response.text();

        throw new Error(
          `Transcription failed (${response.status}): ${
            details.slice(0, 180)
          }`
        );
      }

      const result: TranscriptionResponse =
        await response.json();

      const transcript = result.text?.trim();

      if (!transcript) {
        throw new Error(
          "No speech detected. Please try again."
        );
      }

      if (!mountedRef.current) {
        return;
      }

      setQuestion(transcript);
      setMicrophoneStatus("Transcription complete");
    } catch (reason) {
      if (mountedRef.current) {
        setMicrophoneStatus("Transcription unavailable");
        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to transcribe audio"
        );
      }
    } finally {
      if (mountedRef.current) {
        setTranscribing(false);
      }
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current;

    if (!recorder || recorder.state === "inactive") {
      return;
    }

    setMicrophoneStatus("Processing recording...");
    recorder.stop();
    recordingRef.current = false;
    setRecording(false);
  }

  async function startRecording() {
    if (
      recordingRef.current ||
      busyRef.current ||
      transcribing
    ) {
      return;
    }

    setError(null);
    setSpeechStatus(null);
    setMicrophoneStatus("Requesting microphone...");

    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      setError(
        "Microphone recording is not supported. Use a modern browser on localhost or HTTPS."
      );
      setMicrophoneStatus("Microphone unavailable");
      return;
    }

    try {
      const stream =
        await navigator.mediaDevices.getUserMedia({
          audio: true,
        });

      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = stream;
      chunksRef.current = [];

      const preferredTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ];

      const selectedType = preferredTypes.find((type) =>
        MediaRecorder.isTypeSupported(type)
      );

      const recorder = selectedType
        ? new MediaRecorder(stream, {
            mimeType: selectedType,
          })
        : new MediaRecorder(stream);

      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        if (mountedRef.current) {
          setError("Microphone recording failed.");
          setMicrophoneStatus("Recording failed");
        }

        releaseMicrophone();
      };

      recorder.onstop = () => {
        const mimeType =
          recorder.mimeType || "audio/webm";

        const extension = mimeType.includes("mp4")
          ? "mp4"
          : "webm";

        const audio = new Blob(chunksRef.current, {
          type: mimeType,
        });

        releaseMicrophone();

        if (!mountedRef.current) {
          return;
        }

        if (audio.size === 0) {
          setError("No audio was recorded.");
          setMicrophoneStatus("Recording empty");
          return;
        }

        void transcribeAudio(audio, extension);
      };

      recorder.start(250);
      recordingRef.current = true;
      setRecording(true);
      setMicrophoneStatus(
        "Recording... click again to finish"
      );

      timerRef.current = setTimeout(() => {
        if (
          recorderRef.current?.state === "recording"
        ) {
          stopRecording();
        }
      }, MAX_RECORDING_MS);
    } catch (reason) {
      releaseMicrophone();

      setMicrophoneStatus("Microphone unavailable");
      setError(
        reason instanceof Error
          ? `Microphone error: ${reason.message}`
          : "Unable to access microphone"
      );
    }
  }

  function toggleRecording() {
    if (recordingRef.current) {
      stopRecording();
    } else {
      void startRecording();
    }
  }

  return (
    <main className="min-h-screen bg-[#f5f6f5] px-8 py-8 text-[#292f33]">
      <div className="mx-auto max-w-6xl space-y-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#7b8687]">
            G1 Studio / Communication
          </p>

          <h1 className="mt-2 text-3xl font-bold">
            AI Robot Interaction
          </h1>

          <p className="mt-2 text-sm text-[#657078]">
            Local Ollama AI · Whisper microphone input ·
            Unitree G1 speech
          </p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
          <section className="flex min-h-[580px] flex-col overflow-hidden rounded-xl border border-[#d8dcda] bg-white">
            <div className="flex items-center gap-3 border-b border-[#e2e5e3] p-5">
              <Bot className="h-6 w-6 text-[#00866a]" />

              <div>
                <h2 className="font-bold">
                  G1 Assistant
                </h2>

                <p className="text-xs text-[#738080]">
                  Local language model: g1-assistant
                </p>
              </div>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto p-6">
              {messages.length === 0 && (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <MessageSquare className="mb-4 h-10 w-10 text-[#009b77]" />

                  <h3 className="text-xl font-semibold">
                    Talk to G1
                  </h3>

                  <p className="mt-2 max-w-md text-sm text-[#758080]">
                    Ask about the laboratory, G1 robot,
                    LiDAR perception, or the research project.
                  </p>
                </div>
              )}

              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${
                    message.role === "visitor"
                      ? "justify-end"
                      : "justify-start"
                  }`}
                >
                  <div
                    className={`max-w-[80%] rounded-xl px-5 py-4 text-sm leading-relaxed ${
                      message.role === "visitor"
                        ? "bg-[#00866a] text-white"
                        : "border border-[#e0e4e1] bg-[#f5f7f6] text-[#292f33]"
                    }`}
                  >
                    <p className="mb-2 text-xs font-bold opacity-70">
                      {message.role === "visitor"
                        ? "Visitor"
                        : "G1"}
                    </p>

                    {message.content}
                  </div>
                </div>
              ))}

              {loading && (
                <div className="flex items-center gap-2 text-sm text-[#738080]">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  G1 is generating an answer...
                </div>
              )}
            </div>

            <div className="border-t border-[#e2e5e3] p-5">
              {error && (
                <p className="mb-3 text-sm text-red-600">
                  {error}
                </p>
              )}

              {speechStatus && (
                <p className="mb-3 text-sm text-[#526461]">
                  {speechStatus}
                </p>
              )}

              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void askG1();
                }}
                className="flex gap-3"
              >
                <input
                  type="text"
                  value={question}
                  onChange={(event) =>
                    setQuestion(event.target.value)
                  }
                  maxLength={1000}
                  placeholder="Type or record a question..."
                  disabled={loading || recording || transcribing}
                  className="min-w-0 flex-1 rounded-lg border border-[#ccd2ce] px-4 py-3 text-sm outline-none focus:border-[#009b77] disabled:opacity-60"
                />

                <button
                  type="button"
                  onClick={toggleRecording}
                  disabled={
                    loading ||
                    transcribing ||
                    (recording && !recordingRef.current)
                  }
                  aria-label={
                    recording
                      ? "Stop microphone recording"
                      : "Start microphone recording"
                  }
                  title={
                    recording
                      ? "Stop recording"
                      : "Start recording"
                  }
                  className={`flex items-center justify-center rounded-lg px-4 py-3 transition disabled:opacity-50 ${
                    recording
                      ? "bg-red-600 text-white hover:bg-red-700"
                      : "border border-[#ccd2ce] bg-white text-[#00866a] hover:bg-[#edf7f3]"
                  }`}
                >
                  {recording ? (
                    <MicOff className="h-5 w-5" />
                  ) : transcribing ? (
                    <LoaderCircle className="h-5 w-5 animate-spin" />
                  ) : (
                    <Mic className="h-5 w-5" />
                  )}
                </button>

                <button
                  type="submit"
                  disabled={
                    loading ||
                    transcribing ||
                    recording ||
                    !question.trim()
                  }
                  className="flex items-center gap-2 rounded-lg bg-[#00866a] px-5 py-3 font-semibold text-white transition hover:bg-[#007457] disabled:opacity-50"
                >
                  <Send className="h-4 w-4" />
                  Ask
                </button>
              </form>

              <p
                className={`mt-3 text-xs ${
                  recording
                    ? "font-semibold text-red-600"
                    : "text-[#738080]"
                }`}
              >
                {recording && (
                  <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-red-600" />
                )}

                {microphoneStatus}
                {recording &&
                  " · Maximum 15 seconds"}
              </p>

              <p className="mt-2 text-xs text-[#83908c]">
                Record, stop, review the transcription,
                then click Ask. Microphone audio is sent
                only to the configured local transcription
                service.
              </p>
            </div>
          </section>

          <aside className="space-y-5">
            <div className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <Volume2 className="mb-4 h-7 w-7 text-[#00866a]" />

              <h2 className="font-bold">
                Physical Robot Speech
              </h2>

              <p className="mt-2 text-sm leading-relaxed text-[#738080]">
                Enable this only when the physical G1
                speaker is connected and the lab is
                ready for a spoken response.
              </p>

              <label className="mt-5 flex cursor-pointer items-center gap-3 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={speak}
                  onChange={(event) =>
                    setSpeak(event.target.checked)
                  }
                  className="h-4 w-4 accent-[#00866a]"
                />
                Speak through real G1
              </label>
            </div>

            <div className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <Mic className="mb-4 h-7 w-7 text-[#00866a]" />

              <h2 className="font-bold">
                Visitor Microphone
              </h2>

              <p className="mt-2 text-sm leading-relaxed text-[#738080]">
                Click the microphone to record a question.
                Click again to stop. The recorded audio
                will be transcribed locally using Whisper
                when its backend is configured.
              </p>

              <div className="mt-4 rounded-lg bg-[#f5f7f6] p-3 text-xs text-[#526461]">
                Recording limit: 15 seconds
              </div>
            </div>

            <div className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <h2 className="font-bold">
                System Information
              </h2>

              <dl className="mt-4 space-y-3 text-sm">
                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">
                    AI Engine
                  </dt>
                  <dd className="font-semibold">
                    Ollama
                  </dd>
                </div>

                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">
                    Model
                  </dt>
                  <dd className="font-semibold">
                    g1-assistant
                  </dd>
                </div>

                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">
                    Speech Recognition
                  </dt>
                  <dd className="font-semibold">
                    Whisper API
                  </dd>
                </div>

                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">
                    Speech Output
                  </dt>
                  <dd className="font-semibold">
                    Unitree TTS
                  </dd>
                </div>
              </dl>
            </div>

            <p className="text-xs leading-relaxed text-[#738080]">
              Conversational research prototype. AI
              answers do not control robot locomotion
              or arms.
            </p>
          </aside>
        </div>
      </div>
    </main>
  );
}