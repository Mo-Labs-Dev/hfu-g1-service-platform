"use client";

// Operator PIN (same as the joystick PIN). Asked once per browser tab session,
// checked by the backend, kept in sessionStorage.

import { useCallback, useRef, useState } from "react";
import { postJson } from "@/lib/g1api";

const KEY = "g1_studio_pin";

export function usePin() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const resolver = useRef<((pin: string | null) => void) | null>(null);

  const ensurePin = useCallback((): Promise<string | null> => {
    const saved = typeof window !== "undefined" ? window.sessionStorage.getItem(KEY) : null;
    if (saved) return Promise.resolve(saved);
    setValue("");
    setError("");
    setOpen(true);
    return new Promise((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const forgetPin = useCallback(() => {
    window.sessionStorage.removeItem(KEY);
  }, []);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await postJson("/api/mission/pin/check", { pin: value });
      window.sessionStorage.setItem(KEY, value);
      setOpen(false);
      resolver.current?.(value);
      resolver.current = null;
    } catch (e) {
      setError(e instanceof Error ? e.message : "PIN check failed");
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    setOpen(false);
    resolver.current?.(null);
    resolver.current = null;
  }

  const pinDialog = open ? (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40">
      <div className="w-[340px] rounded-lg bg-white p-6 shadow-xl">
        <div className="h-[3px] w-10 bg-[#009b77]" />
        <h2 className="mt-4 text-[18px] font-bold text-[#292f33]">Operator PIN</h2>
        <p className="mt-1 text-[12px] text-[#657078]">
          Same PIN as the joystick in the G1 Remote app.
        </p>
        <input
          autoFocus
          type="password"
          inputMode="numeric"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
            if (e.key === "Escape") cancel();
          }}
          className="mt-4 w-full rounded border border-[#c6ccd1] px-3 py-2 text-[18px] tracking-[0.4em] outline-none focus:border-[#009b77]"
        />
        {error && <p className="mt-2 text-[12px] font-semibold text-[#d62828]">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={cancel} className="rounded px-4 py-2 text-[13px] font-semibold text-[#566373] hover:bg-[#f0f2f3]">
            Cancel
          </button>
          <button
            onClick={() => void submit()}
            disabled={busy || !value}
            className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-50"
          >
            {busy ? "Checking…" : "Unlock"}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return { ensurePin, forgetPin, pinDialog };
}
