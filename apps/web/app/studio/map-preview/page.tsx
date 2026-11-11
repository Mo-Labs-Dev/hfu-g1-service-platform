"use client";

import { useState } from "react";
import HfuLabMap2D, { type Destination } from "../../../components/navigation/HfuLabMap2D";
import HfuLabMap3D from "../../../components/navigation/HfuLabMap3D";

const INITIAL_DESTINATION: Destination = {
  id: "coffee",
  name: "Coffee Machine",
  position: { x: 0.6, y: 8 },
};

export default function MapPreviewPage() {
  const [selectedDestination, setSelectedDestination] = useState<Destination | null>(INITIAL_DESTINATION);
  const [destinations, setDestinations] = useState<Destination[]>([INITIAL_DESTINATION]);
  const [showTrajectory, setShowTrajectory] = useState(false);

  return (
    <main className="flex h-[calc(100dvh-82px)] min-h-[540px] flex-col overflow-hidden bg-[#f3f5f8] px-2 py-2 text-slate-800 lg:px-3">
      <header className="mb-2 flex h-10 shrink-0 items-center justify-between px-1">
        <h1 className="text-lg font-semibold tracking-tight text-slate-900">Navigation</h1>
        <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-800">Motion locked</span>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden lg:grid-cols-[minmax(175px,1fr)_minmax(0,3fr)_minmax(210px,1.05fr)]">
        <aside className="flex min-h-0 flex-col overflow-y-auto rounded-md border border-slate-300 bg-white p-3 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-800">Map Settings</h2>
          <p className="mt-1 text-[11px] text-slate-500">Session 03 · Saved map</p>
          <div className="mt-5 border-t border-slate-200 pt-4">
            <h3 className="text-xs font-semibold text-slate-700">Map Layers</h3>
            <p className="mt-3 text-xs text-slate-600">3D point cloud and metric grid</p>
            <p className="mt-2 text-[11px] leading-5 text-slate-500">Grid visibility, point size and camera controls are available in the 3D panel.</p>
          </div>
          <label className="mt-5 flex items-center justify-between gap-2 border-t border-slate-200 pt-4 text-xs text-slate-700">
            Historical trajectory
            <input type="checkbox" checked={showTrajectory} onChange={(event) => setShowTrajectory(event.target.checked)} className="h-4 w-4 accent-blue-600" />
          </label>
          <div className="mt-5 border-t border-slate-200 pt-4 text-xs text-slate-600">
            <h3 className="font-semibold text-slate-700">Map reference</h3>
            <p className="mt-2">Resolution: 0.05 m</p>
            <p className="mt-1">3D frame: camera_init</p>
            <p className="mt-1">Alignment: estimated</p>
          </div>
        </aside>

        <div className="grid min-h-0 min-w-0 grid-rows-[minmax(0,3fr)_minmax(0,2fr)] gap-2">
          <section className="min-h-0 min-w-0 overflow-hidden rounded-md border border-slate-300 bg-white shadow-sm">
            <HfuLabMap3D selectedDestination={selectedDestination} />
          </section>
          <section className="min-h-0 min-w-0 overflow-hidden rounded-md border border-slate-300 bg-white shadow-sm">
            <HfuLabMap2D
              compact
              showTrajectory={showTrajectory}
              selectedDestination={selectedDestination}
              onSelectDestination={setSelectedDestination}
              onDestinationsChange={setDestinations}
            />
          </section>
        </div>

        <aside className="flex min-h-0 flex-col overflow-y-auto rounded-md border border-slate-300 bg-white p-3 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-800">Navigation Control</h2>
          <div className="mt-5 border-t border-slate-200 pt-4">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Destination</p>
            <div className="mt-2 space-y-1">
              {destinations.map((destination) => {
                const active = selectedDestination?.id === destination.id;
                return (
                  <button
                    key={destination.id}
                    type="button"
                    onClick={() => setSelectedDestination(destination)}
                    className={`flex w-full items-center gap-2 rounded-md border px-2 py-2 text-left text-xs transition-colors ${active ? "border-blue-200 bg-blue-50 font-semibold text-blue-800" : "border-transparent text-slate-700 hover:bg-slate-50"}`}
                  >
                    <span className={`h-2 w-2 shrink-0 rounded-full ${active ? "bg-blue-600" : "bg-slate-300"}`} />
                    <span className="min-w-0 flex-1 truncate">{destination.name}</span>
                    {active && <span aria-label="Selected">✓</span>}
                  </button>
                );
              })}
              {destinations.length === 0 && <p className="text-xs text-slate-500">Add a destination on the 2D map.</p>}
            </div>
          </div>
          <div className="mt-5 border-t border-slate-200 pt-4">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Start</p>
            <p className="mt-2 text-xs text-slate-700">Recorded G1 position</p>
            <p className="mt-1 font-mono text-[11px] text-slate-500">0.097, 0.019 m</p>
          </div>
          <div className="mt-5 border-t border-slate-200 pt-4">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Selected coordinates</p>
            <p className="mt-2 font-mono text-xs text-slate-700">
              {selectedDestination ? `${selectedDestination.position.x.toFixed(2)} m, ${selectedDestination.position.y.toFixed(2)} m` : "No destination selected"}
            </p>
          </div>
          <div className="mt-5 border-t border-slate-200 pt-4">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Route status</p>
            <p className="mt-2 text-xs font-medium text-amber-800">Not validated</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">Virtual simulation is unavailable until a valid route is found.</p>
          </div>
          <p className="mt-auto border-t border-slate-200 pt-4 text-[11px] text-slate-500">Physical robot movement remains locked.</p>
        </aside>
      </div>
    </main>
  );
}
