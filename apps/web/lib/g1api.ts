// Shared helpers for G1 Studio pages (Mission Control, Lab Map, ...).
// Works on the robot PC (localhost) AND from another PC in the lab network:
// if Studio is opened via http://10.150.68.160:3000 the API is http://10.150.68.160:8000.

export function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const remote = host !== "localhost" && host !== "127.0.0.1";
    if (!env || (remote && /localhost|127\.0\.0\.1/.test(env))) {
      return `${window.location.protocol}//${host}:8000`;
    }
  }
  return env || "http://localhost:8000";
}

function friendly(e: unknown): Error {
  if (e instanceof DOMException && e.name === "AbortError") {
    return new Error("Timed out – the robot PC did not answer in time. Check Mission Control → Services.");
  }
  if (e instanceof TypeError) {
    return new Error("Studio backend not reachable (port 8000).");
  }
  return e instanceof Error ? e : new Error(String(e));
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body?.detail ?? body);
  } catch {
    return `HTTP ${response.status}`;
  }
}

export async function getJson<T>(path: string, timeoutMs = 6000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(await readError(response));
    return (await response.json()) as T;
  } catch (e) {
    throw friendly(e);
  } finally {
    clearTimeout(timer);
  }
}

export async function postJson<T>(path: string, body: unknown = {}, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(await readError(response));
    return (await response.json()) as T;
  } catch (e) {
    throw friendly(e);
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------- types
export type ServiceHealth = {
  id: string;
  name: string;
  port: number;
  ok: boolean;
  detail: string;
  required: boolean;
  ms: number;
};

export type GuideStatus = {
  state: string;
  route: string;
  progress: number;
  message: string;
  leg: string;
  kind?: string;
  stop_index?: number;
  stop_count?: number;
  stop_title?: string;
  alignment?: {
    used?: boolean;
    reason?: string;
    dx?: number;
    dy?: number;
    dyaw_deg?: number;
    fit?: number;
    rmse?: number;
  };
};

export type Overview = {
  time: number;
  services: ServiceHealth[];
  robot: {
    reachable: boolean;
    fsm_id: number | null;
    fsm_name: string;
    walking_mode: boolean;
    estop: boolean | null;
    estop_reason: string | null;
    teleop_active: boolean | null;
    operator: string | null;
    state: string | null;
    gesture: string | null;
    stop_count: number | null;
  };
  guide: GuideStatus | null;
  camera: { ok: boolean; detail: string };
};

export type GuideRoute = {
  name: string;
  title_en: string;
  title_de: string;
  length_m: number;
  kind?: string;
  home_scan?: boolean;
  stops?: { name: string; title_en: string; title_de: string }[];
};

export type ActionInfo = {
  id: string;
  label: string;
  description: string;
  confirm_home: boolean;
};

export type ActionStatus = {
  running: string | null;
  last: { action?: string; label?: string; ok?: boolean; seconds?: number; finished?: string };
  output: string[];
};

export const HFU = {
  green: "#009b77",
  greenDark: "#00866a",
  greenSoft: "#eaf7f2",
  text: "#292f33",
  muted: "#657078",
  border: "#d8dde1",
  danger: "#d62828",
  warning: "#d79616",
};

export async function sendJson<T>(method: "PUT" | "DELETE", path: string, body: unknown = {}, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: method === "DELETE" ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(await readError(response));
    return (await response.json()) as T;
  } catch (e) {
    throw friendly(e);
  } finally {
    clearTimeout(timer);
  }
}
