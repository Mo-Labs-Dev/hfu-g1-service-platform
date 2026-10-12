"use client";

import { useState } from "react";
import { Bot, MessageSquare, Send, Volume2 } from "lucide-react";

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

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

export default function InteractionPage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [speak, setSpeak] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speechStatus, setSpeechStatus] = useState<string | null>(
    null
  );

  async function askG1() {
    const text = question.trim();

    if (!text || loading) return;

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
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to contact G1 AI"
      );
    } finally {
      setLoading(false);
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
            Local Ollama AI · Unitree G1 speech interface
          </p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
          <section className="flex min-h-[580px] flex-col overflow-hidden rounded-xl border border-[#d8dcda] bg-white">
            <div className="flex items-center gap-3 border-b border-[#e2e5e3] p-5">
              <Bot className="h-6 w-6 text-[#00866a]" />

              <div>
                <h2 className="font-bold">G1 Assistant</h2>
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
                    Ask about the laboratory, the G1 robot,
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
                <p className="text-sm text-[#738080]">
                  G1 is generating an answer...
                </p>
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
                  placeholder="Ask G1 a question..."
                  className="min-w-0 flex-1 rounded-lg border border-[#ccd2ce] px-4 py-3 text-sm outline-none focus:border-[#009b77]"
                />

                <button
                  type="submit"
                  disabled={loading || !question.trim()}
                  className="flex items-center gap-2 rounded-lg bg-[#00866a] px-5 py-3 font-semibold text-white transition hover:bg-[#007457] disabled:opacity-50"
                >
                  <Send className="h-4 w-4" />
                  Ask
                </button>
              </form>
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
                speaker is connected and the lab is ready
                for a spoken response.
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
              <h2 className="font-bold">System Information</h2>

              <dl className="mt-4 space-y-3 text-sm">
                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">AI Engine</dt>
                  <dd className="font-semibold">Ollama</dd>
                </div>

                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">Model</dt>
                  <dd className="font-semibold">
                    g1-assistant
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

                <div className="flex justify-between gap-2">
                  <dt className="text-[#738080]">
                    Microphone
                  </dt>
                  <dd className="font-semibold">
                    Not integrated
                  </dd>
                </div>
              </dl>
            </div>

            <p className="text-xs leading-relaxed text-[#738080]">
              Conversational research prototype. AI answers
              do not control robot locomotion or arms.
            </p>
          </aside>
        </div>
      </div>
    </main>
  );
}