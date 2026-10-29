"use client";

import { useRef, useState, type PointerEvent } from "react";

type Direction =
  | "CENTER"
  | "FORWARD"
  | "FORWARD RIGHT"
  | "RIGHT"
  | "BACKWARD RIGHT"
  | "BACKWARD"
  | "BACKWARD LEFT"
  | "LEFT"
  | "FORWARD LEFT";

type G1JoystickProps = {
  label?: string;
  onDirectionChange?: (direction: Direction) => void;
};

const MAX_TRAVEL = 52;

function getDirection(x: number, y: number): Direction {
  if (Math.hypot(x, y) < 0.2) return "CENTER";

  const angle = (Math.atan2(-y, x) * 180) / Math.PI;
  const sector = Math.round(angle / 45);

  const directions: Direction[] = [
    "RIGHT",
    "FORWARD RIGHT",
    "FORWARD",
    "FORWARD LEFT",
    "LEFT",
    "BACKWARD LEFT",
    "BACKWARD",
    "BACKWARD RIGHT",
  ];

  return directions[((sector % 8) + 8) % 8];
}

export default function G1Joystick({
  label = "Movement Joystick",
  onDirectionChange,
}: G1JoystickProps) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const activePointer = useRef<number | null>(null);
  const lastDirection = useRef<Direction>("CENTER");

  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [direction, setDirection] = useState<Direction>("CENTER");

  function updateDirection(next: Direction) {
    if (lastDirection.current === next) return;

    lastDirection.current = next;
    setDirection(next);
    onDirectionChange?.(next);
  }

  function updatePosition(event: PointerEvent<HTMLDivElement>) {
    const element = surfaceRef.current;
    if (!element) return;

    const rect = element.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    const dx = event.clientX - centerX;
    const dy = event.clientY - centerY;
    const distance = Math.hypot(dx, dy);
    const scale = distance > MAX_TRAVEL ? MAX_TRAVEL / distance : 1;

    const x = dx * scale;
    const y = dy * scale;

    setPosition({ x, y });
    updateDirection(getDirection(x / MAX_TRAVEL, y / MAX_TRAVEL));
  }

  function release() {
    activePointer.current = null;
    setPosition({ x: 0, y: 0 });
    updateDirection("CENTER");
  }

  return (
    <div className="flex flex-col items-center gap-4">
      <div
        ref={surfaceRef}
        role="group"
        aria-label={`${label}, visual preview only`}
        onPointerDown={(event) => {
          if (activePointer.current !== null) return;
          if (event.pointerType === "mouse" && event.button !== 0) return;

          activePointer.current = event.pointerId;
          event.currentTarget.setPointerCapture(event.pointerId);
          updatePosition(event);
        }}
        onPointerMove={(event) => {
          if (activePointer.current !== event.pointerId) return;
          updatePosition(event);
        }}
        onPointerUp={(event) => {
          if (activePointer.current === event.pointerId) release();
        }}
        onPointerCancel={(event) => {
          if (activePointer.current === event.pointerId) release();
        }}
        onLostPointerCapture={(event) => {
          if (activePointer.current === event.pointerId) release();
        }}
        className="relative flex h-44 w-44 touch-none select-none items-center justify-center rounded-full border-2 border-[#c5dfd2] bg-[#eef8f3] shadow-inner"
      >
        <div className="absolute h-32 w-32 rounded-full border border-dashed border-[#b3d4c3]" />

        <div className="absolute h-px w-36 bg-[#c2dccd]" />
        <div className="absolute h-36 w-px bg-[#c2dccd]" />

        <span className="absolute top-2 text-xs font-bold text-[#659c83]">
          ↑
        </span>
        <span className="absolute bottom-2 text-xs font-bold text-[#659c83]">
          ↓
        </span>
        <span className="absolute left-2 text-xs font-bold text-[#659c83]">
          ←
        </span>
        <span className="absolute right-2 text-xs font-bold text-[#659c83]">
          →
        </span>

        <div
          className="relative z-10 flex h-16 w-16 items-center justify-center rounded-full border-4 border-[#b0dfca] bg-[#00866a] shadow-lg"
          style={{
            transform: `translate(${position.x}px, ${position.y}px)`,
          }}
        >
          <div className="h-5 w-5 rounded-full bg-[#51bc9d]" />
        </div>
      </div>

      <div className="text-center">
        <p className="text-sm font-semibold text-[#294d3f]">{label}</p>
        <p className="mt-1 text-xs font-medium text-[#00866a]">
          {direction === "CENTER" ? "Centered" : direction.replaceAll("_", " ")}
        </p>
        <p className="mt-1 text-xs text-[#84938c]">
          Visual preview · No robot commands
        </p>
      </div>
    </div>
  );
}
