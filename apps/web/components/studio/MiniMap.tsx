"use client";

// 2D lab map (Session 03 occupancy grid) with G1's pose, a walked path and blocked points.
// Used by Live View and Replay. Coordinates are map-frame metres.

import { useEffect, useMemo, useState } from "react";
import { apiBase, getJson } from "@/lib/g1api";

type MapInfo = { width_px: number; height_px: number; resolution: number; origin: [number, number] };
export type Pose = { x: number; y: number; yaw?: number | null; quality?: string };

let infoCache: MapInfo | null = null;

export default function MiniMap({
  pose,
  path = [],
  ghostPath = [],
  blocked = [],
  height = 520,
  fit = "path",
}: {
  pose?: Pose | null;
  path?: [number, number][];
  ghostPath?: [number, number][];
  blocked?: [number, number][];
  height?: number;
  fit?: "map" | "path";
}) {
  const [info, setInfo] = useState<MapInfo | null>(infoCache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (infoCache) return;
    getJson<MapInfo>("/api/map/info")
      .then((i) => {
        infoCache = i;
        setInfo(i);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const px = useMemo(() => {
    if (!info) return null;
    const [ox, oy] = info.origin;
    return (x: number, y: number): [number, number] => [(x - ox) / info.resolution, info.height_px - 1 - (y - oy) / info.resolution];
  }, [info]);

  // ignore impossible positions (diverged odometry) instead of zooming to them
  const safePose = useMemo(() => {
    if (!pose || !info || !px) return null;
    const [cx, cy] = px(pose.x, pose.y);
    const m = 10 / info.resolution;
    const ok = Number.isFinite(cx) && Number.isFinite(cy) && cx > -m && cy > -m && cx < info.width_px + m && cy < info.height_px + m;
    return ok ? pose : null;
  }, [pose, info, px]);

  // zoom to the interesting part (path + pose) with a margin, otherwise the whole map
  const viewBox = useMemo(() => {
    if (!info || !px) return "0 0 100 100";
    const pts = [...path, ...ghostPath, ...blocked, ...(safePose ? [[safePose.x, safePose.y] as [number, number]] : [])].map(([x, y]) => px(x, y));
    if (fit === "map" || pts.length === 0) return `0 0 ${info.width_px} ${info.height_px}`;
    const m = 3 / info.resolution; // 3 m margin
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    let x0 = Math.min(...xs) - m, x1 = Math.max(...xs) + m, y0 = Math.min(...ys) - m, y1 = Math.max(...ys) + m;
    const minSpan = 8 / info.resolution;
    if (x1 - x0 < minSpan) { const c = (x0 + x1) / 2; x0 = c - minSpan / 2; x1 = c + minSpan / 2; }
    if (y1 - y0 < minSpan) { const c = (y0 + y1) / 2; y0 = c - minSpan / 2; y1 = c + minSpan / 2; }
    return `${x0} ${y0} ${x1 - x0} ${y1 - y0}`;
  }, [info, px, path, ghostPath, blocked, safePose, fit]);

  if (error) return <div className="flex items-center justify-center text-[13px] text-[#a33]" style={{ height }}>Map: {error}</div>;
  if (!info || !px) return <div className="flex items-center justify-center text-[13px] text-[#8a949c]" style={{ height }}>Loading map…</div>;

  const r = 0.25 / info.resolution;
  const line = (pts: [number, number][]) => pts.map(([x, y]) => px(x, y).join(",")).join(" ");
  const robot = safePose ? px(safePose.x, safePose.y) : null;
  const yaw = safePose?.yaw ?? 0;

  return (
    <svg viewBox={viewBox} style={{ height, width: "100%" }} className="rounded-lg bg-[#f4f5f4]" preserveAspectRatio="xMidYMid meet">
      <image href={`${apiBase()}/api/map/image.png`} x={0} y={0} width={info.width_px} height={info.height_px} style={{ imageRendering: "pixelated" }} />
      {ghostPath.length > 1 && (
        <polyline points={line(ghostPath)} fill="none" stroke="#9fb4c4" strokeWidth={r * 0.5} strokeLinejoin="round" strokeDasharray={`${r} ${r * 0.6}`} />
      )}
      {path.length > 1 && (
        <polyline points={line(path)} fill="none" stroke="#009b77" strokeWidth={r * 0.6} strokeLinejoin="round" strokeLinecap="round" />
      )}
      {path.length > 0 && (() => { const [sx, sy] = px(path[0][0], path[0][1]); return <circle cx={sx} cy={sy} r={r * 0.7} fill="#36414b" />; })()}
      {blocked.map(([x, y], i) => {
        const [bx, by] = px(x, y);
        return <circle key={i} cx={bx} cy={by} r={r * 0.9} fill="#e0a100" stroke="#fff" strokeWidth={r * 0.2} />;
      })}
      {robot && (
        <g transform={`translate(${robot[0]} ${robot[1]}) rotate(${(-yaw * 180) / Math.PI})`}>
          <circle r={r * 1.6} fill="#009b77" opacity={0.18} />
          <polygon points={`${r * 1.5},0 ${-r},${r} ${-r * 0.5},0 ${-r},${-r}`} fill="#00664f" stroke="#fff" strokeWidth={r * 0.2} />
        </g>
      )}
    </svg>
  );
}
