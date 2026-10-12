
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type WorkflowStep = {
  id?: string;
  name?: string;
  action?: string;
  action_type?: string;
  type?: string;
  parameters?: Record<string, unknown>;
};

type Workflow = {
  id: string;
  name: string;
  description?: string;
  status?: string;
  steps?: WorkflowStep[];
  source: "demonstration" | "custom";
};

const API = "http://localhost:8000";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [backendOnline, setBackendOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadWorkflows() {
      try {
        const [demoResponse, customResponse] = await Promise.all([
          fetch(`${API}/api/demonstrations`, {
            cache: "no-store",
          }),
          fetch(`${API}/api/workflows`, {
            cache: "no-store",
          }),
        ]);

        if (!demoResponse.ok || !customResponse.ok) {
          throw new Error("Unable to load workflows.");
        }

        const demoData = await demoResponse.json();
        const customData = await customResponse.json();

        const demos = Array.isArray(demoData)
          ? demoData
          : demoData.demonstrations || [];

        const custom = Array.isArray(customData)
          ? customData
          : [];

        if (!active) return;

        setWorkflows([
          ...custom.map((item: Workflow) => ({
            ...item,
            source: "custom" as const,
          })),
          ...demos.map((item: Workflow) => ({
            ...item,
            source: "demonstration" as const,
          })),
        ]);

        setBackendOnline(true);
        setError(null);
      } catch (err) {
        console.error(err);

        if (!active) return;

        setBackendOnline(false);
        setError("The workflow service is currently unavailable.");
      } finally {
        if (active) setLoading(false);
      }
    }

    loadWorkflows();

    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1600px] px-6 py-12 md:px-16">
          <div className="flex flex-wrap items-end justify-between gap-8">
            <div>
              <div className="h-[3px] w-12 bg-[#009b77]" />

              <p className="mt-6 text-[10px] font-bold uppercase tracking-[0.22em] text-[#8a9499]">
                Workflow Engineering
              </p>

              <h1 className="mt-4 text-[40px] font-bold tracking-[-0.04em] text-[#2d3337]">
                Workflows
              </h1>

              <p className="mt-4 max-w-[620px] text-[14px] leading-6 text-[#707b81]">
                Create, configure and execute reusable humanoid robot
                workflows using the G1 task engine.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-3">
                <span
                  className={`h-2 w-2 rounded-full ${
                    backendOnline
                      ? "bg-[#009b77]"
                      : "bg-[#b8bec1]"
                  }`}
                />

                <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#7c868b]">
                  {backendOnline
                    ? "Backend Online"
                    : "Backend Offline"}
                </span>
              </div>

              <Link
                href="/studio/workflows/new"
                className="inline-flex h-[44px] items-center gap-4 bg-[#009b77] px-6 text-[10px] font-bold uppercase tracking-[0.15em] text-white transition hover:bg-[#00866a]"
              >
                <span className="text-[17px] font-light">+</span>
                New Workflow
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1600px] px-6 py-10 md:px-16">
        <div className="mb-6 flex items-center justify-between border-b border-[#dfe3e1] pb-5">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#626d73]">
              Workflow Library
            </p>

            <p className="mt-1 text-[9px] text-[#9aa2a6]">
              Saved workflows and predefined demonstrations
            </p>
          </div>

          {!loading && !error && (
            <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#929b9f]">
              {workflows.length} Workflows
            </p>
          )}
        </div>

        {loading && (
          <div className="flex min-h-[320px] items-center justify-center border border-[#dfe3e1] bg-white">
            <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#899398]">
              Loading Workflows
            </p>
          </div>
        )}

        {!loading && error && (
          <div className="flex min-h-[320px] items-center justify-center border border-[#dfe3e1] bg-white px-6 text-center">
            <div>
              <h2 className="text-[16px] font-bold text-[#4e585d]">
                Workflow service unavailable
              </h2>

              <p className="mt-2 text-[11px] text-[#929b9f]">
                {error}
              </p>

              <p className="mt-2 text-[10px] text-[#a1a8ab]">
                Start the G1 Studio backend and reload this page.
              </p>
            </div>
          </div>
        )}

        {!loading && !error && workflows.length === 0 && (
          <div className="flex min-h-[320px] items-center justify-center border border-[#dfe3e1] bg-white text-center">
            <div>
              <h2 className="text-[15px] font-bold text-[#505a60]">
                No workflows available
              </h2>

              <p className="mt-2 text-[11px] text-[#939ca0]">
                Create a workflow to begin configuring G1 robot tasks.
              </p>
            </div>
          </div>
        )}

        {!loading && !error && (
          <div className="space-y-5">
            {workflows.map((workflow, index) => (
              <WorkflowCard
                key={`${workflow.source}-${workflow.id}`}
                workflow={workflow}
                index={index}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function WorkflowCard({
  workflow,
  index,
}: {
  workflow: Workflow;
  index: number;
}) {
  const steps = workflow.steps || [];
  const custom = workflow.source === "custom";

  return (
    <article className="group border border-[#dce1de] bg-white transition hover:border-[#c7ceca] hover:shadow-[0_10px_35px_rgba(35,48,42,0.055)]">
      <div className="flex flex-wrap items-start justify-between gap-5 px-7 pb-5 pt-7">
        <div className="flex gap-6">
          <span className="pt-[2px] text-[9px] font-bold tracking-[0.18em] text-[#b0b7ba]">
            {String(index + 1).padStart(2, "0")}
          </span>

          <div>
            <h2 className="text-[18px] font-bold tracking-[-0.02em] text-[#343c40]">
              {workflow.name}
            </h2>

            <p className="mt-2 max-w-[700px] text-[11px] leading-5 text-[#8b959a]">
              {workflow.description ||
                "Reusable G1 humanoid robot workflow."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="h-1.5 w-1.5 rounded-full bg-[#009b77]" />

          <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#657078]">
            {custom
              ? workflow.status || "draft"
              : "Predefined"}
          </span>
        </div>
      </div>

      <div className="border-y border-[#edf0ee] bg-[#fafbfa] px-7 py-5">
        <div className="flex flex-wrap items-center gap-y-3">
          {steps.map((step, stepIndex) => {
            const label =
              step.action_type ||
              step.action ||
              step.type ||
              step.name ||
              "Action";

            return (
              <div
                key={step.id || `${workflow.id}-${stepIndex}`}
                className="flex items-center"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-[#d8ddda] bg-white text-[8px] font-bold text-[#7d878c]">
                  {String(stepIndex + 1).padStart(2, "0")}
                </span>

                <span className="ml-3 text-[9px] font-bold uppercase tracking-[0.11em] text-[#606b70]">
                  {label.replaceAll("_", " ")}
                </span>

                {stepIndex < steps.length - 1 && (
                  <span className="mx-5 text-[#b8bfbc]">→</span>
                )}
              </div>
            );
          })}

          {steps.length === 0 && (
            <span className="text-[10px] text-[#9aa2a6]">
              No steps configured
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between px-7 py-5">
        <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#929b9f]">
          {steps.length} {steps.length === 1 ? "Step" : "Steps"}
        </span>

      <Link
  href={`/studio/workflows/${encodeURIComponent(workflow.id)}`}
  className="text-[10px] font-bold uppercase tracking-[0.13em] text-[#007f63] hover:text-[#005f4a]"
>
  Open Workflow →
</Link>
      </div>
    </article>
  );
}
