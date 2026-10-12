
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type Action =
  | "speak"
  | "navigate"
  | "wait"
  | "return_home"
  | "detect_object"
  | "pick"
  | "place"
  | "manipulate"
  | "clean"
  | "verify";

type Step = {
  id: string;
  name: string;
  action: Action;
  parameters: Record<string, string | number>;
};

type Location = {
  id: string;
  name: string;
  target: string;
  configured: boolean;
};

const API = "http://localhost:8000";

const ACTIONS: { value: Action; label: string }[] = [
  { value: "speak", label: "Speak" },
  { value: "navigate", label: "Navigate" },
  { value: "wait", label: "Wait" },
  { value: "return_home", label: "Return Home" },
  { value: "detect_object", label: "Detect Object" },
  { value: "pick", label: "Pick Object" },
  { value: "place", label: "Place Object" },
  { value: "manipulate", label: "Manipulate" },
  { value: "clean", label: "Clean" },
  { value: "verify", label: "Verify" },
];

const REQUIRED: Partial<Record<Action, string[]>> = {
  speak: ["text"],
  navigate: ["location_id"],
  detect_object: ["object_name"],
  pick: ["object_name"],
  place: ["target"],
  manipulate: ["target", "operation"],
  clean: ["target"],
  verify: ["target", "condition"],
  wait: ["seconds"],
};

function createStep(action: Action = "speak"): Step {
  return {
    id: crypto.randomUUID(),
    name: ACTIONS.find((item) => item.value === action)?.label || action,
    action,
    parameters:
      action === "wait"
        ? { seconds: 1 }
        : action === "speak"
          ? { text: "" }
          : {},
  };
}

const inputClass =
  "w-full border border-[#dce1de] bg-white px-4 py-3 text-[13px] text-[#343c40] outline-none transition focus:border-[#009b77]";

const labelClass =
  "mb-2 block text-[10px] font-bold uppercase tracking-[0.12em] text-[#778187]";

export default function NewWorkflowPage() {
  const router = useRouter();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<"draft" | "ready">("draft");
  const [steps, setSteps] = useState<Step[]>([
    createStep("speak"),
  ]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadLocations() {
      try {
        const response = await fetch(`${API}/api/locations`, {
          cache: "no-store",
        });

        if (!response.ok) return;

        const data = await response.json();

        if (Array.isArray(data)) {
          setLocations(data);
        }
      } catch (err) {
        console.error("Unable to load locations:", err);
      }
    }

    loadLocations();
  }, []);

  function updateStep(id: string, updates: Partial<Step>) {
    setSteps((current) =>
      current.map((step) =>
        step.id === id ? { ...step, ...updates } : step
      )
    );
  }

  function updateParameter(
    id: string,
    key: string,
    value: string | number
  ) {
    setSteps((current) =>
      current.map((step) =>
        step.id === id
          ? {
              ...step,
              parameters: {
                ...step.parameters,
                [key]: value,
              },
            }
          : step
      )
    );
  }

  function changeAction(id: string, action: Action) {
    setSteps((current) =>
      current.map((step) =>
        step.id === id
          ? { ...createStep(action), id }
          : step
      )
    );
  }

  function moveStep(index: number, direction: -1 | 1) {
    const destination = index + direction;

    if (destination < 0 || destination >= steps.length) {
      return;
    }

    setSteps((current) => {
      const updated = [...current];

      [updated[index], updated[destination]] = [
        updated[destination],
        updated[index],
      ];

      return updated;
    });
  }

  function removeStep(id: string) {
    setSteps((current) =>
      current.filter((step) => step.id !== id)
    );
  }

  async function saveWorkflow() {
    setError(null);

    if (!name.trim()) {
      setError("Please enter a workflow name.");
      return;
    }

    if (steps.length === 0) {
      setError("Add at least one action before saving.");
      return;
    }

    for (const step of steps) {
      if (!step.name.trim()) {
        setError("Every step needs a name.");
        return;
      }

      for (const key of REQUIRED[step.action] || []) {
        const value = step.parameters[key];

        if (
          value === undefined ||
          value === null ||
          String(value).trim() === ""
        ) {
          setError(
            `The "${step.name}" step requires "${key}".`
          );
          return;
        }
      }

      if (step.action === "wait") {
        const seconds = Number(step.parameters.seconds);

        if (
          !Number.isFinite(seconds) ||
          seconds < 0 ||
          seconds > 300
        ) {
          setError("Wait duration must be between 0 and 300 seconds.");
          return;
        }
      }
    }

    setSaving(true);

    try {
      const response = await fetch(`${API}/api/workflows`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          status,
          steps: steps.map((step) => ({
            name: step.name.trim(),
            action: step.action,
            parameters: step.parameters,
          })),
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);

        throw new Error(
          data?.detail
            ? JSON.stringify(data.detail)
            : `Unable to save workflow (${response.status}).`
        );
      }

      router.push("/studio/workflows");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save workflow."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1400px] px-6 py-10 md:px-16">
          <Link
            href="/studio/workflows"
            className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#00866a]"
          >
            ← Back to Workflows
          </Link>

          <div className="mt-8 h-[3px] w-12 bg-[#009b77]" />

          <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#8a9499]">
            Workflow Engineering / Create
          </p>

          <h1 className="mt-3 text-[36px] font-bold tracking-[-0.04em] text-[#2d3337]">
            New Workflow
          </h1>

          <p className="mt-3 text-[13px] text-[#707b81]">
            Configure reusable robot actions without writing code.
          </p>
        </div>
      </section>

      <main className="mx-auto max-w-[1400px] px-6 py-10 md:px-16">
        <div className="grid gap-8 lg:grid-cols-[1fr_300px]">
          <div className="space-y-8">
            <section className="border border-[#dce1de] bg-white p-7">
              <h2 className="text-[16px] font-bold text-[#343c40]">
                Workflow Information
              </h2>

              <div className="mt-6 space-y-5">
                <div>
                  <label className={labelClass}>
                    Workflow Name
                  </label>

                  <input
                    className={inputClass}
                    value={name}
                    maxLength={150}
                    placeholder="Visitor Coffee Assistance"
                    onChange={(event) =>
                      setName(event.target.value)
                    }
                  />
                </div>

                <div>
                  <label className={labelClass}>
                    Description
                  </label>

                  <textarea
                    className={`${inputClass} min-h-[100px]`}
                    value={description}
                    maxLength={2000}
                    placeholder="Describe what the robot should do..."
                    onChange={(event) =>
                      setDescription(event.target.value)
                    }
                  />
                </div>

                <div>
                  <label className={labelClass}>
                    Definition Status
                  </label>

                  <select
                    className={inputClass}
                    value={status}
                    onChange={(event) =>
                      setStatus(
                        event.target.value as "draft" | "ready"
                      )
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="ready">Ready</option>
                  </select>

                  <p className="mt-2 text-[10px] text-[#929b9f]">
                    Ready means the definition is prepared for review,
                    not that the physical robot has been validated.
                  </p>
                </div>
              </div>
            </section>

            <section>
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h2 className="text-[16px] font-bold text-[#343c40]">
                    Action Sequence
                  </h2>

                  <p className="mt-1 text-[11px] text-[#929b9f]">
                    Steps execute from top to bottom.
                  </p>
                </div>

                <span className="text-[10px] font-bold text-[#929b9f]">
                  {steps.length} Steps
                </span>
              </div>

              <div className="space-y-4">
                {steps.map((step, index) => (
                  <div
                    key={step.id}
                    className="border border-[#dce1de] bg-white p-6"
                  >
                    <div className="mb-6 flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#009b77]">
                        Step {String(index + 1).padStart(2, "0")}
                      </span>

                      <div className="flex gap-3">
                        <button
                          type="button"
                          disabled={index === 0}
                          onClick={() => moveStep(index, -1)}
                          className="text-[12px] text-[#657078] disabled:opacity-30"
                          title="Move up"
                        >
                          ↑
                        </button>

                        <button
                          type="button"
                          disabled={index === steps.length - 1}
                          onClick={() => moveStep(index, 1)}
                          className="text-[12px] text-[#657078] disabled:opacity-30"
                          title="Move down"
                        >
                          ↓
                        </button>

                        <button
                          type="button"
                          onClick={() => removeStep(step.id)}
                          className="text-[10px] font-bold text-[#b65353]"
                        >
                          Remove
                        </button>
                      </div>
                    </div>

                    <div className="grid gap-5 md:grid-cols-2">
                      <div>
                        <label className={labelClass}>
                          Step Name
                        </label>

                        <input
                          className={inputClass}
                          value={step.name}
                          maxLength={150}
                          onChange={(event) =>
                            updateStep(step.id, {
                              name: event.target.value,
                            })
                          }
                        />
                      </div>

                      <div>
                        <label className={labelClass}>
                          Robot Action
                        </label>

                        <select
                          className={inputClass}
                          value={step.action}
                          onChange={(event) =>
                            changeAction(
                              step.id,
                              event.target.value as Action
                            )
                          }
                        >
                          {ACTIONS.map((action) => (
                            <option
                              key={action.value}
                              value={action.value}
                            >
                              {action.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>

                    {(REQUIRED[step.action] || []).map((key) => (
                      <div key={key} className="mt-5">
                        <label className={labelClass}>
                          {key.replaceAll("_", " ")}
                        </label>

                        {key === "location_id" ? (
                          <select
                            className={inputClass}
                            value={String(
                              step.parameters.location_id || ""
                            )}
                            onChange={(event) =>
                              updateParameter(
                                step.id,
                                key,
                                event.target.value
                              )
                            }
                          >
                            <option value="">
                              Select a location
                            </option>

                            {locations.map((location) => (
                              <option
                                key={location.id}
                                value={location.target}
                              >
                                {location.name}
                                {location.configured
                                  ? " (Calibrated)"
                                  : " (Unconfigured)"}
                              </option>
                            ))}
                          </select>
                        ) : key === "text" ? (
                          <textarea
                            className={`${inputClass} min-h-[90px]`}
                            value={String(
                              step.parameters[key] || ""
                            )}
                            placeholder="Enter what G1 should say..."
                            onChange={(event) =>
                              updateParameter(
                                step.id,
                                key,
                                event.target.value
                              )
                            }
                          />
                        ) : (
                          <input
                            className={inputClass}
                            type={
                              key === "seconds" ? "number" : "text"
                            }
                            min={
                              key === "seconds" ? 0 : undefined
                            }
                            max={
                              key === "seconds" ? 300 : undefined
                            }
                            step={
                              key === "seconds" ? 0.5 : undefined
                            }
                            value={
                              step.parameters[key] ?? ""
                            }
                            onChange={(event) =>
                              updateParameter(
                                step.id,
                                key,
                                key === "seconds"
                                  ? event.target.value === ""
                                    ? ""
                                    : Number(event.target.value)
                                  : event.target.value
                              )
                            }
                          />
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>

              <button
                type="button"
                disabled={steps.length >= 100}
                onClick={() =>
                  setSteps((current) => [
                    ...current,
                    createStep(),
                  ])
                }
                className="mt-5 w-full border border-dashed border-[#b7cec5] bg-white px-5 py-5 text-[11px] font-bold uppercase tracking-[0.13em] text-[#00866a] transition hover:bg-[#f0f8f4] disabled:opacity-40"
              >
                + Add Action
              </button>
            </section>
          </div>

          <aside>
            <div className="sticky top-6 border border-[#dce1de] bg-white p-6">
              <h2 className="text-[14px] font-bold text-[#343c40]">
                Workflow Summary
              </h2>

              <div className="mt-6 space-y-4 border-y border-[#edf0ee] py-5 text-[12px] text-[#657078]">
                <div className="flex justify-between">
                  <span>Steps</span>
                  <strong>{steps.length}</strong>
                </div>

                <div className="flex justify-between">
                  <span>Status</span>
                  <strong className="capitalize">{status}</strong>
                </div>

                <div className="flex justify-between">
                  <span>Execution</span>
                  <strong>Not started</strong>
                </div>
              </div>

              {error && (
                <p
                  role="alert"
                  className="mb-4 border border-red-200 bg-red-50 p-3 text-[11px] leading-5 text-red-700"
                >
                  {error}
                </p>
              )}

              <button
                type="button"
                disabled={saving}
                onClick={saveWorkflow}
                className="w-full bg-[#009b77] px-5 py-4 text-[11px] font-bold uppercase tracking-[0.14em] text-white transition hover:bg-[#00866a] disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Workflow →"}
              </button>

              <Link
                href="/studio/workflows"
                className="mt-4 block text-center text-[10px] font-bold uppercase tracking-[0.12em] text-[#929b9f]"
              >
                Cancel
              </Link>

              <p className="mt-6 text-[10px] leading-5 text-[#929b9f]">
                Saving stores the workflow definition in PostgreSQL.
                It does not execute robot movements.
              </p>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
