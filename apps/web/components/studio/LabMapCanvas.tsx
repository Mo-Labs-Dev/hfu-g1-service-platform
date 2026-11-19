"use client";

// Lab map canvas: Session 03 map + routes + stops + HOME + live G1.
// Mouse wheel = zoom, drag = pan. In "place HOME" mode: press on the HOME spot,
// drag in the direction G1 faces, release.

import { useCallback, useEffect, useRef, useState } from "react";

export type MapInfo = {
  width_px: number;
  height_px: number;
  resolution: number;
  origin: [number, number];
};

export type MapStop = {
  name: string;
  title_en: string;
  title_de: string;
  text_en?: string;
  text_de?: string;
  map: [number, number] | null;
  yaw: number | null;
};

export type MapRoute = {
  name: string;
  title_en: string;
  title_de: string;
  kind: string;
  length_m: number;
  created: string;
  home_scan: boolean;
  alignment: { source: string; fit?: number; rmse?: number; ok?: boolean };
  path: [number, number][] | null;
  stops: MapStop[];
  intro_en?: string;
  intro_de?: string;
};

export type Pose = { x: number; y: number; yaw: number };

export const ROUTE_COLORS = ["#009b77", "#2f6fdb", "#d97706", "#9333ea", "#db2777", "#0891b2"];

type Props = {
  info: MapInfo;
  imageUrl: string;
  routes: MapRoute[];
  visible: Record<string, boolean>;
  home: Pose | null;
  live: (Pose & { source: string }) | null;
  showLabels: boolean;
  placingHome: boolean;
  draftHome: Pose | null;
  onDraftHome: (p: Pose) => void;
  selectedStop?: string | null;
  blockedSpots?: [number, number][];
  overlayPaths?: { points: [number, number][]; color: string; dash?: boolean; width?: number }[];
  overlayCircles?: { x: number; y: number; r: number; color: string; label?: string }[];
  simPose?: Pose | null;
  onMapClick?: (p: { x: number; y: number }) => void;
};

export default function LabMapCanvas(props: Props) {
  const { info, imageUrl, routes, visible, home, live, showLabels, placingHome, draftHome, onDraftHome } = props;
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [size, setSize] = useState({ w: 800, h: 600 });
  // view: screen = (pixel - center) * scale + screenCenter
  const [view, setView] = useState<{ cx: number; cy: number; scale: number } | null>(null);
  const drag = useRef<{ x: number; y: number; cx: number; cy: number; mode: "pan" | "home"; start?: Pose; moved?: boolean } | null>(
    null,
  );

  // world (m) <-> map pixel
  const toPx = useCallback(
    (x: number, y: number) => ({
      px: (x - info.origin[0]) / info.resolution,
      py: info.height_px - (y - info.origin[1]) / info.resolution,
    }),
    [info],
  );
  const toWorld = useCallback(
    (px: number, py: number) => ({
      x: info.origin[0] + px * info.resolution,
      y: info.origin[1] + (info.height_px - py) * info.resolution,
    }),
    [info],
  );

  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      imgRef.current = img;
      setImgLoaded(true);
    };
    img.src = imageUrl;
  }, [imageUrl]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // initial view: fit the map, or centre on HOME if known
  useEffect(() => {
    if (view || !size.w) return;
    const fit = Math.min(size.w / info.width_px, size.h / info.height_px) * 0.95;
    if (home) {
      const p = toPx(home.x, home.y);
      setView({ cx: p.px, cy: p.py, scale: Math.max(fit, 1.4) });
    } else {
      setView({ cx: info.width_px / 2, cy: info.height_px / 2, scale: fit });
    }
  }, [size, info, home, view, toPx]);

  const screen = useCallback(
    (px: number, py: number) => {
      const v = view!;
      return { sx: (px - v.cx) * v.scale + size.w / 2, sy: (py - v.cy) * v.scale + size.h / 2 };
    },
    [view, size],
  );

  // ------------------------------------------------------------ draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !view) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#eef1f3";
    ctx.fillRect(0, 0, size.w, size.h);

    if (imgLoaded && imgRef.current) {
      const tl = screen(0, 0);
      ctx.imageSmoothingEnabled = view.scale < 2;
      ctx.drawImage(imgRef.current, tl.sx, tl.sy, info.width_px * view.scale, info.height_px * view.scale);
    }

    const w2s = (x: number, y: number) => {
      const p = toPx(x, y);
      return screen(p.px, p.py);
    };
    const mPx = view.scale / info.resolution; // screen px per metre

    // 1 m grid scale bar
    ctx.fillStyle = "#36414b";
    ctx.fillRect(16, size.h - 22, mPx * 2, 4);
    ctx.font = "11px Arial";
    ctx.fillText("2 m", 16, size.h - 28);

    // routes
    routes.forEach((r, i) => {
      if (!visible[r.name] || !r.path || r.path.length < 2) return;
      const color = ROUTE_COLORS[i % ROUTE_COLORS.length];
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(2, Math.min(5, mPx * 0.08));
      ctx.lineJoin = "round";
      ctx.setLineDash(r.alignment.source === "scan" ? [] : [8, 6]);
      ctx.beginPath();
      r.path.forEach(([x, y], k) => {
        const s = w2s(x, y);
        if (k === 0) ctx.moveTo(s.sx, s.sy);
        else ctx.lineTo(s.sx, s.sy);
      });
      ctx.stroke();
      ctx.setLineDash([]);

      // direction arrow at 1/3 of the path
      const k = Math.floor(r.path.length / 3);
      if (k > 0) {
        const a = w2s(...r.path[k - 1]);
        const b = w2s(...r.path[k]);
        const ang = Math.atan2(b.sy - a.sy, b.sx - a.sx);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(b.sx + Math.cos(ang) * 9, b.sy + Math.sin(ang) * 9);
        ctx.lineTo(b.sx + Math.cos(ang + 2.5) * 8, b.sy + Math.sin(ang + 2.5) * 8);
        ctx.lineTo(b.sx + Math.cos(ang - 2.5) * 8, b.sy + Math.sin(ang - 2.5) * 8);
        ctx.fill();
      }

      // stops
      r.stops.forEach((st, n) => {
        if (!st.map) return;
        const s = w2s(st.map[0], st.map[1]);
        if (st.yaw !== null) {
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(s.sx, s.sy);
          ctx.lineTo(s.sx + Math.cos(-st.yaw) * 22, s.sy + Math.sin(-st.yaw) * 22);
          ctx.stroke();
        }
        ctx.fillStyle = props.selectedStop === `${r.name}/${st.name}` ? "#292f33" : color;
        ctx.beginPath();
        ctx.arc(s.sx, s.sy, 11, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = "bold 11px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(n + 1), s.sx, s.sy + 0.5);
        if (showLabels) {
          ctx.textAlign = "left";
          ctx.font = "bold 12px Arial";
          const label = st.title_en || st.name;
          const tw = ctx.measureText(label).width;
          ctx.fillStyle = "rgba(255,255,255,0.92)";
          ctx.fillRect(s.sx + 14, s.sy - 9, tw + 8, 18);
          ctx.fillStyle = "#292f33";
          ctx.fillText(label, s.sx + 18, s.sy);
        }
      });
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
    });

    // spots where G1 had to wait ("blocked" heatmap from the run log)
    (props.blockedSpots || []).forEach(([bx, by]) => {
      const s = w2s(bx, by);
      ctx.fillStyle = "rgba(214,40,40,0.28)";
      ctx.beginPath();
      ctx.arc(s.sx, s.sy, Math.max(7, mPx * 0.35), 0, Math.PI * 2);
      ctx.fill();
    });

    // overlays (simulation / planner)
    (props.overlayPaths || []).forEach((op) => {
      if (op.points.length < 2) return;
      ctx.strokeStyle = op.color;
      ctx.lineWidth = op.width ?? 3;
      ctx.setLineDash(op.dash ? [6, 5] : []);
      ctx.beginPath();
      op.points.forEach(([x, y], k) => {
        const s = w2s(x, y);
        if (k === 0) ctx.moveTo(s.sx, s.sy);
        else ctx.lineTo(s.sx, s.sy);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    });
    (props.overlayCircles || []).forEach((c) => {
      const s = w2s(c.x, c.y);
      ctx.fillStyle = c.color;
      ctx.beginPath();
      ctx.arc(s.sx, s.sy, Math.max(5, c.r * mPx), 0, Math.PI * 2);
      ctx.fill();
      if (c.label) {
        ctx.fillStyle = "#292f33";
        ctx.font = "bold 11px Arial";
        ctx.fillText(c.label, s.sx + Math.max(5, c.r * mPx) + 4, s.sy + 4);
      }
    });

    // HOME (saved + draft)
    const drawHome = (p: Pose, draft: boolean) => {
      const s = w2s(p.x, p.y);
      ctx.fillStyle = draft ? "rgba(215,150,22,0.9)" : "#292f33";
      ctx.beginPath();
      ctx.moveTo(s.sx, s.sy - 13);
      ctx.lineTo(s.sx + 12, s.sy - 2);
      ctx.lineTo(s.sx + 8, s.sy - 2);
      ctx.lineTo(s.sx + 8, s.sy + 10);
      ctx.lineTo(s.sx - 8, s.sy + 10);
      ctx.lineTo(s.sx - 8, s.sy - 2);
      ctx.lineTo(s.sx - 12, s.sy - 2);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = draft ? "#d79616" : "#292f33";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(s.sx, s.sy);
      ctx.lineTo(s.sx + Math.cos(-p.yaw) * 34, s.sy + Math.sin(-p.yaw) * 34);
      ctx.stroke();
      ctx.font = "bold 11px Arial";
      ctx.fillText(draft ? "HOME (new)" : "HOME", s.sx + 14, s.sy + 18);
    };
    if (home) drawHome(home, false);
    if (draftHome) drawHome(draftHome, true);

    // simulated G1 (blue)
    if (props.simPose) {
      const sp = props.simPose;
      const s = w2s(sp.x, sp.y);
      const r = Math.max(9, mPx * 0.25);
      ctx.fillStyle = "rgba(47,111,219,0.18)";
      ctx.beginPath();
      ctx.arc(s.sx, s.sy, r * 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#2f6fdb";
      ctx.beginPath();
      ctx.moveTo(s.sx + Math.cos(-sp.yaw) * r * 1.6, s.sy + Math.sin(-sp.yaw) * r * 1.6);
      ctx.lineTo(s.sx + Math.cos(-sp.yaw + 2.4) * r, s.sy + Math.sin(-sp.yaw + 2.4) * r);
      ctx.lineTo(s.sx + Math.cos(-sp.yaw - 2.4) * r, s.sy + Math.sin(-sp.yaw - 2.4) * r);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = "#2f6fdb";
      ctx.font = "bold 12px Arial";
      ctx.fillText("SIM", s.sx + r + 6, s.sy - r);
    }

    // live G1
    if (live) {
      const s = w2s(live.x, live.y);
      const r = Math.max(9, mPx * 0.25);
      ctx.fillStyle = "rgba(0,155,119,0.18)";
      ctx.beginPath();
      ctx.arc(s.sx, s.sy, r * 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#009b77";
      ctx.beginPath();
      ctx.moveTo(s.sx + Math.cos(-live.yaw) * r * 1.6, s.sy + Math.sin(-live.yaw) * r * 1.6);
      ctx.lineTo(s.sx + Math.cos(-live.yaw + 2.4) * r, s.sy + Math.sin(-live.yaw + 2.4) * r);
      ctx.lineTo(s.sx + Math.cos(-live.yaw - 2.4) * r, s.sy + Math.sin(-live.yaw - 2.4) * r);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = "#00866a";
      ctx.font = "bold 12px Arial";
      ctx.fillText("G1", s.sx + r + 6, s.sy - r);
    }
  }, [view, size, imgLoaded, routes, visible, home, live, showLabels, draftHome, info, screen, toPx, props.selectedStop, props.blockedSpots, props.overlayPaths, props.overlayCircles, props.simPose]);

  // ------------------------------------------------------------ interaction
  function eventToWorld(e: React.MouseEvent) {
    const rect = canvasRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const v = view!;
    const px = (sx - size.w / 2) / v.scale + v.cx;
    const py = (sy - size.h / 2) / v.scale + v.cy;
    return toWorld(px, py);
  }

  function onMouseDown(e: React.MouseEvent) {
    if (!view) return;
    if (placingHome) {
      const w = eventToWorld(e);
      const start = { x: w.x, y: w.y, yaw: draftHome?.yaw ?? 0 };
      drag.current = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, mode: "home", start };
      onDraftHome(start);
      return;
    }
    drag.current = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, mode: "pan" };
  }

  function onMouseMove(e: React.MouseEvent) {
    const d = drag.current;
    if (!d || !view) return;
    if (d.mode === "pan") {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) d.moved = true;
      setView({ ...view, cx: d.cx - (e.clientX - d.x) / view.scale, cy: d.cy - (e.clientY - d.y) / view.scale });
    } else if (d.start) {
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      if (Math.hypot(dx, dy) > 6) onDraftHome({ ...d.start, yaw: Math.atan2(-dy, dx) });
    }
  }

  function onMouseUp(e?: React.MouseEvent) {
    const d = drag.current;
    drag.current = null;
    if (e && d && d.mode === "pan" && !d.moved && props.onMapClick && view) {
      props.onMapClick(eventToWorld(e));
    }
  }

  function onWheel(e: React.WheelEvent) {
    if (!view) return;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const rect = canvasRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const px = (sx - size.w / 2) / view.scale + view.cx;
    const py = (sy - size.h / 2) / view.scale + view.cy;
    const scale = Math.min(20, Math.max(0.2, view.scale * factor));
    setView({ scale, cx: px - (sx - size.w / 2) / scale, cy: py - (sy - size.h / 2) / scale });
  }

  function centerOn(p: Pose | null) {
    if (!p || !view) return;
    const q = toPx(p.x, p.y);
    setView({ ...view, cx: q.px, cy: q.py, scale: Math.max(view.scale, 2) });
  }

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden rounded-md">
      <canvas
        ref={canvasRef}
        style={{ width: size.w, height: size.h, cursor: placingHome || props.onMapClick ? "crosshair" : "grab" }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={() => onMouseUp()}
        onWheel={onWheel}
      />
      <div className="absolute right-3 top-3 flex flex-col gap-2">
        <button
          onClick={() => view && setView({ ...view, scale: Math.min(20, view.scale * 1.3) })}
          className="h-9 w-9 rounded bg-white text-[18px] font-bold text-[#36414b] shadow"
        >
          +
        </button>
        <button
          onClick={() => view && setView({ ...view, scale: Math.max(0.2, view.scale / 1.3) })}
          className="h-9 w-9 rounded bg-white text-[18px] font-bold text-[#36414b] shadow"
        >
          −
        </button>
        <button
          title="Centre on G1"
          onClick={() => centerOn(live)}
          disabled={!live}
          className="h-9 w-9 rounded bg-white text-[11px] font-bold text-[#00866a] shadow disabled:opacity-40"
        >
          G1
        </button>
        <button
          title="Centre on HOME"
          onClick={() => centerOn(home)}
          disabled={!home}
          className="h-9 w-9 rounded bg-white text-[14px] font-bold text-[#36414b] shadow disabled:opacity-40"
        >
          ⌂
        </button>
      </div>
      {placingHome && (
        <div className="absolute left-3 top-3 rounded bg-[#fff6e5] px-3 py-2 text-[12px] font-semibold text-[#9a6812] shadow">
          Press on the HOME spot, drag in the direction G1 faces, release.
        </div>
      )}
    </div>
  );
}
