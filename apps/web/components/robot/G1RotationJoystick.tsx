"use client";

import { useRef, useState, type PointerEvent } from "react";
import { RotateCcw, RotateCw } from "lucide-react";

type Rotation = "LEFT" | "CENTER" | "RIGHT";

export default function G1RotationJoystick() {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const activePointer = useRef<number | null>(null);

  const [position, setPosition] = useState(0);
  const [rotation, setRotation] = useState<Rotation>("CENTER");

  function updatePosition(event: PointerEvent<HTMLDivElement>) {
    if (!surfaceRef.current) return;

    const rect = surfaceRef.current.getBoundingClientRect();
    const center = rect.left + rect.width / 2;

    const x = Math.max(
      -52,
      Math.min(52, event.clientX - center)
    );

    setPosition(x);
    setRotation(x < -10 ? "LEFT" : x > 10 ? "RIGHT" : "CENTER");
  }

  function reset() {
    activePointer.current = null;
    setPosition(0);
    setRotation("CENTER");
  }

  return (
    <div className="flex flex-col items-center gap-4">
      <div
        ref={surfaceRef}
        role="group"
        aria-label="Rotation joystick, visual preview only"
        onPointerDown={(event) => {
          if (activePointer.current !== null) return;
          if (event.pointerType === "mouse" && event.button !== 0) return;

          activePointer.current = event.pointerId;
          event.currentTarget.setPointerCapture(event.pointerId);
          updatePosition(event);
        }}
        onPointerMove={(event) => {
          if (activePointer.current === event.pointerId) {
            updatePosition(event);
          }
        }}
        onPointerUp={(event) => {
          if (activePointer.current === event.pointerId) reset();
        }}
        onPointerCancel={(event) => {
          if (activePointer.current === event.pointerId) reset();
        }}
        onLostPointerCapture={(event) => {
          if (activePointer.current === event.pointerId) reset();
        }}
        className="relative flex h-44 w-44 touch-none select-none items-center justify-center rounded-full border-2 border-[#c5dfd2] bg-[#eef8f3] shadow-inner"
      >
        <div className="absolute h-32 w-32 rounded-full border border-dashed border-[#b3d4c3]" />

        <div className="absolute flex w-36 justify-between text-[#00866a]">
          <RotateCcw className="h-5 w-5" />
          <RotateCw className="h-5 w-5" />
        </div>

        <div
          className="relative z-10 flex h-16 w-16 items-center justify-center rounded-full border-4 border-[#b0dfca] bg-[#00866a] shadow-lg"
          style={{ transform: `translateX(${position}px)` }}
        >
          <div className="h-5 w-5 rounded-full bg-[#51bc9d]" />
        </div>
      </div>

      <div className="text-center">
        <p className="text-sm font-semibold text-[#294d3f]">
          Rotation · Yaw
        </p>
        <p className="mt-1 text-xs font-medium text-[#00866a]">
          {rotation === "CENTER"
            ? "Centered"
            : rotation === "LEFT"
              ? "Rotate Left"
              : "Rotate Right"}
        </p>
        <p className="mt-1 text-xs text-[#84938c]">
          Visual preview · No robot commands
        </p>
      </div>
    </div>
  );
}
