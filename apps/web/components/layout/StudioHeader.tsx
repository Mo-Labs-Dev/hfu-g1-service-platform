"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navigation = [
  {
    label: "Dashboard",
    href: "/studio",
  },
  {
    label: "Workflows",
    href: "/studio/workflows",
  },
  {
    label: "Locations",
    href: "/studio/locations",
  },
  {
    label: "Vision",
    href: "/studio/vision",
  },
  {
    label: "LiDAR",
    href: "/studio/lidar",
  },
  {
    label: "Interaction",
    href: "/studio/interaction",
  },
  {
    label: "Robot Control",
    href: "/studio/control",
  },
  {
    label: "Task History",
    href: "/studio/history",
  },
  {
    label: "Settings",
    href: "/studio/settings",
  },
];

export default function StudioHeader() {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === "/studio") {
      return pathname === "/studio";
    }

    return pathname.startsWith(href);
  }

  return (
    <header
      className="
        sticky
        top-0
        z-50
        h-[88px]
        w-full
        border-b
        border-[#c3c7c5]
        bg-[#d7d8d6]
      "
    >
      <div
        className="
          mx-auto
          flex
          h-full
          w-full
          max-w-[1750px]
          items-stretch
          px-8
        "
      >
        {/* ================================================= */}
        {/* BRAND */}
        {/* ================================================= */}

        <div className="flex shrink-0 items-center">
          <Link
            href="/"
            className="flex shrink-0 items-center"
          >
            <img
              src="/hfu-logo.svg"
              alt="Hochschule Furtwangen University"
              className="h-[58px] w-auto"
            />
          </Link>

          <div className="mx-6 h-[52px] w-px bg-[#b6bab8]" />

          <div className="flex flex-col justify-center">
            <Link
              href="/studio"
              className="
                text-[25px]
                font-bold
                leading-none
                tracking-[-0.04em]
                text-[#292f33]
              "
            >
              G1 Studio
            </Link>

            <p
              className="
                mt-2
                text-[10px]
                font-medium
                text-[#657078]
              "
            >
              Engineering Platform
            </p>
          </div>
        </div>

        {/* ================================================= */}
        {/* PLATFORM NAVIGATION */}
        {/* ================================================= */}

        <nav
          className="
            ml-auto
            flex
            h-full
            items-stretch
          "
        >
          {navigation.map((item) => {
            const active = isActive(item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`
                  group
                  relative
                  flex
                  h-full
                  items-center
                  whitespace-nowrap
                  px-[18px]
                  text-[15px]
                  font-bold
                  tracking-[-0.02em]
                  transition-colors
                  duration-200
                  ${
                    active
                      ? "text-[#00866a]"
                      : "text-[#292f33] hover:text-[#009b77]"
                  }
                `}
              >
                {item.label}

                <span
                  className={`
                    absolute
                    bottom-0
                    left-[18px]
                    right-[18px]
                    h-[3px]
                    bg-[#009b77]
                    transition-opacity
                    duration-200
                    ${
                      active
                        ? "opacity-100"
                        : "opacity-0 group-hover:opacity-50"
                    }
                  `}
                />
              </Link>
            );
          })}
        </nav>

        {/* ================================================= */}
        {/* USER */}
        {/* ================================================= */}

        <div
          className="
            ml-4
            flex
            shrink-0
            items-center
            border-l
            border-[#bcc0be]
            pl-6
          "
        >
          <button
            type="button"
            className="group flex items-center gap-3"
          >
            <div
              className="
                flex
                h-11
                w-11
                items-center
                justify-center
                rounded-full
                bg-[#009b77]
                text-[12px]
                font-bold
                text-white
                transition-transform
                duration-200
                group-hover:scale-105
              "
            >
              MS
            </div>

            <span className="text-[10px] text-[#50595e]">
              ▼
            </span>
          </button>
        </div>
      </div>
    </header>
  );
}