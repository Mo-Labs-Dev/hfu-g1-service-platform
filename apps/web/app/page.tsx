"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Header from "@/components/layout/Header";
import G1Model from "@/components/robot/G1Model";

type RobotStatus = {
  connected?: boolean;
  battery?: number;
  mode?: string;
  current_location?: string;
  current_action?: string;
};

export default function HomePage() {
  const [robotStatus, setRobotStatus] =
    useState<RobotStatus | null>(null);

  const [backendOnline, setBackendOnline] =
    useState(false);

  const [startupText, setStartupText] =
    useState("INITIALIZING G1 PLATFORM...");

  useEffect(() => {
    const timers = [
      setTimeout(() => {
        setStartupText("CONNECTING ROBOT INTERFACE...");
      }, 900),

      setTimeout(() => {
        setStartupText("ROBOT INTERFACE READY");
      }, 1800),

      setTimeout(() => {
        setStartupText("SYSTEM READY");
      }, 2700),
    ];

    return () => {
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, []);

  useEffect(() => {
    async function loadRobotStatus() {
      try {
        const response = await fetch(
          "http://localhost:8000/api/robot/status",
          {
            cache: "no-store",
          }
        );

        if (!response.ok) {
          throw new Error("Robot status unavailable");
        }

        const data = await response.json();

        setRobotStatus(data);
        setBackendOnline(true);
      } catch {
        setBackendOnline(false);
      }
    }

    loadRobotStatus();

    const interval = setInterval(
      loadRobotStatus,
      5000
    );

    return () => clearInterval(interval);
  }, []);

  const mode =
    robotStatus?.mode?.toUpperCase() ||
    (backendOnline ? "SIMULATION" : "OFFLINE");

  const robotConnected =
    backendOnline &&
    robotStatus?.connected !== false;

  return (
    <div className="flex min-h-screen flex-col bg-white">

      {/* ================================================= */}
      {/* LANDING HEADER */}
      {/* ================================================= */}

      <Header />


      {/* ================================================= */}
      {/* MAIN HERO */}
      {/* ================================================= */}

      <main className="relative flex flex-1 items-center overflow-hidden">

        <div
          className="
            mx-auto
            grid
            w-full
            max-w-[1500px]
            grid-cols-[48%_52%]
            items-center
            px-16
          "
        >

          {/* ============================================= */}
          {/* LEFT CONTENT */}
          {/* ============================================= */}

          <section className="relative z-10 py-16">

            {/* HFU GREEN ACCENT */}
            <div className="mb-7 h-[3px] w-12 bg-[#009b77]" />

            <p
              className="
                text-[11px]
                font-bold
                uppercase
                tracking-[0.24em]
                text-[#879198]
              "
            >
              Humanoid Robot Engineering Platform
            </p>


            {/* TITLE */}
            <h1
              className="
                mt-7
                text-[56px]
                font-bold
                tracking-[-0.045em]
                text-[#2d3337]
              "
            >
              G1 Studio
            </h1>


            {/* DESCRIPTION */}
            <p
              className="
                mt-7
                max-w-[570px]
                text-[17px]
                leading-8
                text-[#657078]
              "
            >
              Engineering, configuration and management environment
              for the Unitree G1 humanoid robot.
            </p>


            {/* =========================================== */}
            {/* SYSTEM STATUS */}
            {/* =========================================== */}

            <div className="mt-9 flex items-center gap-3">

              <span
                className={`
                  h-2.5
                  w-2.5
                  rounded-full
                  ${
                    robotConnected
                      ? "bg-[#009b77]"
                      : "bg-[#b5babd]"
                  }
                `}
              />

              <span
                className="
                  text-[11px]
                  font-bold
                  uppercase
                  tracking-[0.14em]
                  text-[#566168]
                "
              >
                {startupText}
              </span>

            </div>


            {/* =========================================== */}
            {/* TECHNICAL STATUS */}
            {/* =========================================== */}

            <div
              className="
                mt-5
                flex
                flex-wrap
                items-center
                gap-x-5
                gap-y-2
                text-[10px]
                font-semibold
                uppercase
                tracking-[0.12em]
                text-[#8a9398]
              "
            >

              <span>
                G1-29DOF
              </span>

              <span className="h-3 w-px bg-[#d6dad8]" />

              <span>
                {mode}
              </span>

              <span className="h-3 w-px bg-[#d6dad8]" />

              <span>
                {backendOnline
                  ? "Backend Connected"
                  : "Backend Offline"}
              </span>

              {robotStatus?.battery !== undefined && (
                <>
                  <span className="h-3 w-px bg-[#d6dad8]" />

                  <span>
                    Battery {robotStatus.battery}%
                  </span>
                </>
              )}

            </div>


            {/* =========================================== */}
            {/* ENTER STUDIO */}
            {/* =========================================== */}

            <div className="mt-10">

              <Link
                href="/studio"
                className="
                  inline-flex
                  items-center
                  gap-7
                  border
                  border-[#009b77]
                  bg-[#009b77]
                  px-7
                  py-4
                  text-[11px]
                  font-bold
                  uppercase
                  tracking-[0.16em]
                  text-white
                  transition-all
                  duration-300
                  hover:bg-[#007e62]
                  hover:shadow-[0_10px_28px_rgba(0,155,119,0.20)]
                "
              >
                Enter G1 Studio

                <span className="text-[15px]">
                  →
                </span>

              </Link>

            </div>

          </section>


          {/* ============================================= */}
          {/* RIGHT SIDE — DIGITAL G1 */}
          {/* ============================================= */}

          <section
            className="
              relative
              flex
              min-h-[690px]
              items-center
              justify-center
            "
          >

            {/* OUTER CIRCLE */}
            <div
              className="
                pointer-events-none
                absolute
                h-[650px]
                w-[650px]
                rounded-full
                border
                border-[#eef1ef]
                bg-[#f5f7f6]
                shadow-[0_20px_60px_rgba(45,51,55,0.035)]
              "
            />

            {/* INNER RING */}
            <div
              className="
                pointer-events-none
                absolute
                h-[540px]
                w-[540px]
                rounded-full
                border
                border-white
              "
            />

            {/* 3D ROBOT */}
            <div className="relative z-10 h-[650px] w-[650px]">
              <G1Model />
            </div>

          </section>

        </div>

      </main>


      {/* ================================================= */}
      {/* FOOTER */}
      {/* ================================================= */}

      <footer
        className="
          shrink-0
          border-t
          border-[#c9cbc9]
          bg-[#d7d8d6]
        "
      >

        <div
          className="
            mx-auto
            flex
            min-h-[70px]
            max-w-[1500px]
            items-center
            justify-between
            px-16
          "
        >

          {/* LEFT */}
          <div>

            <p
              className="
                text-[10px]
                font-semibold
                text-[#687278]
              "
            >
              © 2026 G1 Studio · Institut für Produkt und Service Engineering
            </p>

            <p
              className="
                mt-1
                text-[9px]
                text-[#8f989d]
              "
            >
              Hochschule Furtwangen University
            </p>

          </div>


          {/* RIGHT */}
          <div className="text-right">

            <p
              className="
                text-[10px]
                font-semibold
                text-[#687278]
              "
            >
              Robert-Gerwig-Platz 1
            </p>

            <p
              className="
                mt-1
                text-[9px]
                text-[#8f989d]
              "
            >
              78120 Furtwangen · Germany
            </p>

          </div>

        </div>

      </footer>

    </div>
  );
}