
"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

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

type SavedWorkflow = {
  id: string;
  name: string;
  description: string;
  status: "draft" | "ready";
  steps: {
    id: string;
    name: string;
    action: Action;
    parameters: Record<string, string | number>;
  }[];
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  wait: ["seconds"],
  detect_object: ["object_name"],
  pick: ["object_name"],
  place: ["target"],
  manipulate: ["target", "operation"],
  clean: ["target"],
  verify: ["target", "condition"],
};

const inputClass =
  "w-full border border-[#dce1de] bg-white px-4 py-3 text-[13px] text-[#343c40] outline-none focus:border-[#009b77]";

const labelClass =
  "mb-2 block text-[10px] font-bold uppercase tracking-[0.12em] text-[#778187]";

function newStep(action: Action = "speak"): Step {
  return {
    id: crypto.randomUUID(),
    name: ACTIONS.find((item) => item.value === action)?.label || action,
    action,
    parameters:
      action === "speak"
        ? { text: "" }
        : action === "wait"
          ? { seconds: 1 }
          : {},
  };
}

export default function EditWorkflowPage() {
  const params = useParams();
  const router = useRouter();

  const id = Array.isArray(params.id)
    ? params.id[0]
    : String(params.id || "");

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<"draft" | "ready">("draft");
  const [steps, setSteps] = useState<Step[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${API}/api/workflows/${encodeURIComponent(id)}`,
        { cache: "no-store" }
      );

      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "Saved workflow not found."
            : "Unable to load workflow."
        );
      }

      const data: SavedWorkflow = await response.json();

      setName(data.name);
      setDescription(data.description || "");
      setStatus(data.status);
      setSteps(
        [...data.steps]
          .map((step) => ({
            id: step.id,
            name: step.name,
            action: step.action,
            parameters: { ...step.parameters },
          }))
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load workflow."
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    async function loadLocations() {
      try {
        const response = await fetch(`${API}/api/locations`, {
          cache: "no-store",
        });

        if (!response.ok) return;
        const data = await response.json();
        if (Array.isArray(data)) setLocations(data);
      } catch {
        // Location selection remains editable if API is unavailable.
      }
    }

    void loadLocations();
  }, []);

  function updateStep(stepId: string, updates: Partial<Step>) {
    setSteps((previous) =>
      previous.map((step) =>
        step.id === stepId ? { ...step, ...updates } : step
      )
    );
  }

  function changeAction(stepId: string, action: Action) {
    setSteps((previous) =>
      previous.map((step) =>
        step.id === stepId
          ? { ...newStep(action), id: step.id }
          : step
      )
    );
  }

  function updateParameter(
    stepId: string,
    key: string,
    value: string | number
  ) {
    setSteps((previous) =>
      previous.map((step) =>
        step.id === stepId
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

  function moveStep(index: number, direction: -1 | 1) {
    const destination = index + direction;

    if (destination < 0 || destination >= steps.length) return;

    setSteps((previous) => {
      const next = [...previous];
      [next[index], next[destination]] = [
        next[destination],
        next[index],
      ];
      return next;
    });
  }

  function validate(): string | null {
    if (!name.trim()) return "Workflow name is required.";
    if (steps.length === 0) return "Add at least one step.";
    if (steps.length > 100) return "Maximum 100 steps allowed.";

    for (const step of steps) {
      if (!step.name.trim()) return "Every step requires a name.";

      for (const key of REQUIRED[step.action] || []) {
        const value = step.parameters[key];
        if (
          value === undefined ||
          value === null ||
          String(value).trim() === ""
        ) {
          return `${step.name}: ${key} is required.`;
        }
      }

      if (step.action === "wait") {
        const seconds = Number(step.parameters.seconds);
        if (
          !Number.isFinite(seconds) ||
          seconds < 0 ||
          seconds > 300
        ) {
          return "Wait duration must be between 0 and 300 seconds.";
        }
      }
    }

    return null;
  }

  async function save() {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(
        `${API}/api/workflows/${encodeURIComponent(id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
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
        }
      );

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          body?.detail
            ? JSON.stringify(body.detail)
            : `Unable to update workflow (${response.status}).`
        );
      }

      router.push(`/studio/workflows/${encodeURIComponent(id)}`);
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to save changes."
      );
    } finally {
      setSaving(false);
    }
  }

  async function deleteWorkflow() {
    setDeleting(true);
    setError(null);

    try {
      const response = await fetch(
        `${API}/api/workflows/${encodeURIComponent(id)}`,
        { method: "DELETE" }
      );

      if (!response.ok) {
        throw new Error(
          `Unable to delete workflow (${response.status}).`
        );
      }

      router.push("/studio/workflows");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to delete workflow."
      );
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center bg-[#f7f8f7] text-sm text-[#899398]">
        Loading workflow editor...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1400px] px-6 py-10 md:px-16">
          <Link
            href={`/studio/workflows/${encodeURIComponent(id)}`}
            className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#00866a]"
          >
            ← Back to Workflow
          </Link>
          <div className="mt-8 h-[3px] w-12 bg-[#009b77]" />
          <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#8a9499]">
            Workflow Engineering / Edit
          </p>
          <h1 className="mt-3 text-[36px] font-bold tracking-[-0.04em] text-[#2d3337]">
            Edit Workflow
          </h1>
          <p className="mt-3 text-[13px] text-[#707b81]">
            Update your reusable robot task definition.
          </p>
        </div>
      </section>

      <main className="mx-auto max-w-[1400px] px-6 py-10 md:px-16">
        {error && (
          <div
            role="alert"
            className="mb-6 border border-red-200 bg-red-50 p-4 text-[12px] text-red-700"
          >
            {error}
          </div>
        )}

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="space-y-8">
            <section className="border border-[#dce1de] bg-white p-7">
              <h2 className="text-[16px] font-bold text-[#343c40]">
                Workflow Information
              </h2>

              <div className="mt-6 space-y-5">
                <div>
                  <label className={labelClass}>Workflow Name</label>
                  <input
                    className={inputClass}
                    value={name}
                    maxLength={150}
                    onChange={(event) => setName(event.target.value)}
                  />
                </div>

                <div>
                  <label className={labelClass}>Description</label>
                  <textarea
                    className={`${inputClass} min-h-[100px]`}
                    value={description}
                    maxLength={2000}
                    onChange={(event) =>
                      setDescription(event.target.value)
                    }
                  />
                </div>

                <div>
                  <label className={labelClass}>Status</label>
                  <select
                    className={inputClass}
                    value={status}
                    onChange={(event) =>
                      setStatus(event.target.value as "draft" | "ready")
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="ready">Ready</option>
                  </select>
                  <p className="mt-2 text-[10px] text-[#929b9f]">
                    Ready does not mean physical robot validation.
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
                    Actions execute in this order.
                  </p>
                </div>
                <span className="text-[10px] text-[#929b9f]">
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

                      <div className="flex gap-4">
                        <button
                          type="button"
                          disabled={index === 0}
                          onClick={() => moveStep(index, -1)}
                          className="text-sm text-[#657078] disabled:opacity-30"
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          disabled={index === steps.length - 1}
                          onClick={() => moveStep(index, 1)}
                          className="text-sm text-[#657078] disabled:opacity-30"
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setSteps((previous) =>
                              previous.filter(
                                (item) => item.id !== step.id
                              )
                            )
                          }
                          className="text-[10px] font-bold text-[#b65353]"
                        >
                          Remove
                        </button>
                      </div>
                    </div>

                    <div className="grid gap-5 md:grid-cols-2">
                      <div>
                        <label className={labelClass}>Step Name</label>
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
                        <label className={labelClass}>Robot Action</label>
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
                      <div className="mt-5" key={key}>
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
                            <option value="">Select a location</option>
                            {step.parameters.location_id &&
                              !locations.some(
                                (location) =>
                                  location.target ===
                                  step.parameters.location_id
                              ) && (
                                <option
                                  value={String(
                                    step.parameters.location_id
                                  )}
                                >
                                  {String(
                                    step.parameters.location_id
                                  )} (Existing value)
                                </option>
                              )}
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
                              step.parameters[key] ?? ""
                            )}
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
                            min={key === "seconds" ? 0 : undefined}
                            max={key === "seconds" ? 300 : undefined}
                            step={key === "seconds" ? 0.5 : undefined}
                            value={step.parameters[key] ?? ""}
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
                  setSteps((previous) => [
                    ...previous,
                    newStep(),
                  ])
                }
                className="mt-5 w-full border border-dashed border-[#b7cec5] bg-white px-5 py-5 text-[11px] font-bold uppercase tracking-[0.13em] text-[#00866a] hover:bg-[#f0f8f4] disabled:opacity-40"
              >
                + Add Action
              </button>
            </section>
          </div>

          <aside>
            <div className="sticky top-6 border border-[#dce1de] bg-white p-6">
              <h2 className="text-[14px] font-bold text-[#343c40]">
                Workflow Controls
              </h2>

              <div className="my-6 space-y-4 border-y border-[#edf0ee] py-5 text-[12px] text-[#657078]">
                <div className="flex justify-between">
                  <span>Steps</span>
                  <strong>{steps.length}</strong>
                </div>
                <div className="flex justify-between">
                  <span>Status</span>
                  <strong className="capitalize">{status}</strong>
                </div>
              </div>

              <button
                type="button"
                disabled={saving || deleting}
                onClick={() => void save()}
                className="w-full bg-[#009b77] px-5 py-4 text-[11px] font-bold uppercase tracking-[0.14em] text-white disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Changes →"}
              </button>

              <Link
                href={`/studio/workflows/${encodeURIComponent(id)}`}
                className="mt-4 block text-center text-[10px] font-bold uppercase text-[#929b9f]"
              >
                Cancel
              </Link>

              <div className="mt-8 border-t border-[#edf0ee] pt-6">
                <h3 className="text-[11px] font-bold text-[#b65353]">
                  Danger Zone
                </h3>
                <p className="mt-2 text-[10px] leading-5 text-[#929b9f]">
                  Deleting a workflow permanently removes its saved
                  definition and steps.
                </p>
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  disabled={saving || deleting}
                  className="mt-4 w-full border border-[#d9a8a8] px-4 py-3 text-[10px] font-bold uppercase text-[#b65353] disabled:opacity-50"
                >
                  Delete Workflow
                </button>
              </div>
            </div>
          </aside>
        </div>
      </main>

      {confirmDelete && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-5"
        >
          <div className="w-full max-w-[440px] bg-white p-8 shadow-xl">
            <h2
              id="delete-title"
              className="text-[20px] font-bold text-[#343c40]"
            >
              Delete this workflow?
            </h2>
            <p className="mt-4 text-[13px] leading-6 text-[#707b81]">
              You are about to permanently delete{" "}
              <strong>{name}</strong> and all its configured steps.
              This cannot be undone.
            </p>
            <div className="mt-8 flex justify-end gap-3">
              <button
                type="button"
                disabled={deleting}
                onClick={() => setConfirmDelete(false)}
                className="border border-[#dce1de] px-5 py-3 text-[11px] font-bold text-[#657078]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => void deleteWorkflow()}
                className="bg-[#b65353] px-5 py-3 text-[11px] font-bold text-white disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Yes, Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
