"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type NavigationItem = {
  name: string;
  href: string;
  icon: string;
};

const robotNavigation: NavigationItem[] = [
  {
    name: "Dashboard",
    href: "/",
    icon: "▦",
  },
  {
    name: "Guide",
    href: "/guide",
    icon: "⌖",
  },
  {
    name: "Workflows",
    href: "/demonstration",
    icon: "▶",
  },
  {
    name: "Vision",
    href: "/vision",
    icon: "◉",
  },
  {
    name: "Interaction",
    href: "/interaction",
    icon: "◎",
  },
  {
    name: "Robot Control",
    href: "/control",
    icon: "◆",
  },
];

const systemNavigation: NavigationItem[] = [
  {
    name: "Logs",
    href: "/logs",
    icon: "≡",
  },
  {
    name: "Settings",
    href: "/settings",
    icon: "⚙",
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  function renderNavigationItem(item: NavigationItem) {
    const active = pathname === item.href;

    return (
      <Link
        key={item.href}
        href={item.href}
        className={`
          group relative flex h-10 items-center gap-3 rounded-md px-3
          text-[13px] font-medium transition-all duration-150
          ${
            active
              ? "bg-white text-[#007c61] shadow-[0_1px_2px_rgba(0,0,0,0.05)]"
              : "text-[#53606c] hover:bg-white/70 hover:text-[#17202a]"
          }
        `}
      >
        {/* Active indicator */}
        {active && (
          <span className="absolute bottom-2 left-0 top-2 w-[3px] rounded-r bg-[#009b77]" />
        )}

        {/* Icon */}
        <span
          className={`
            flex w-5 items-center justify-center text-[12px]
            ${
              active
                ? "text-[#009b77]"
                : "text-[#89939c] group-hover:text-[#596570]"
            }
          `}
        >
          {item.icon}
        </span>

        {/* Label */}
        <span>{item.name}</span>
      </Link>
    );
  }

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-[240px] flex-col border-r border-[#d5dade] bg-[#eef1f3]">

      {/* =====================================================
          HFU / IPSE BRANDING
      ====================================================== */}

      <div className="border-b border-[#d5dade] px-5 pb-5 pt-5">

        <div className="flex h-[58px] items-center">
          <img
            src="/hfu-logo.svg"
            alt="Hochschule Furtwangen University"
            className="max-h-[58px] w-auto max-w-full object-contain object-left"
          />
        </div>

        <div className="mt-4 border-t border-[#d9dee2] pt-4">

          <p className="text-[11px] font-semibold tracking-[0.08em] text-[#37424c]">
            IPSE
          </p>

          <p className="mt-1 text-[9px] leading-[14px] text-[#7e8993]">
            Institut für Produkt und
            <br />
            Service Engineering
          </p>

        </div>

      </div>


      {/* =====================================================
          NAVIGATION
      ====================================================== */}

      <div className="flex-1 overflow-y-auto px-3 py-5">

        {/* Robot Platform */}

        <p className="mb-2 px-3 text-[9px] font-semibold uppercase tracking-[0.16em] text-[#89939c]">
          Robot Platform
        </p>

        <nav className="space-y-1">
          {robotNavigation.map(renderNavigationItem)}
        </nav>


        {/* Divider */}

        <div className="mx-3 my-5 border-t border-[#d9dee2]" />


        {/* System */}

        <p className="mb-2 px-3 text-[9px] font-semibold uppercase tracking-[0.16em] text-[#89939c]">
          System
        </p>

        <nav className="space-y-1">
          {systemNavigation.map(renderNavigationItem)}
        </nav>

      </div>


      {/* =====================================================
          ROBOT / SYSTEM STATUS
      ====================================================== */}

      <div className="border-t border-[#d5dade] p-4">

        <div className="overflow-hidden rounded-lg border border-[#d5dade] bg-white">

          {/* Robot status */}

          <div className="flex items-center justify-between px-3 py-3">

            <div className="flex items-center gap-2.5">

              {/* Status dot */}

              <span className="h-2 w-2 rounded-full bg-[#d29a2e]" />

              <div>

                <p className="text-[11px] font-semibold text-[#36414b]">
                  Unitree G1
                </p>

                <p className="mt-0.5 text-[9px] text-[#8a949e]">
                  Simulation Mode
                </p>

              </div>

            </div>


            {/* SIM badge */}

            <span className="rounded border border-[#e3b34f] bg-[#fff8e8] px-2 py-1 text-[8px] font-bold text-[#9a6812]">
              SIM
            </span>

          </div>


          {/* Backend */}

          <div className="flex items-center justify-between border-t border-[#e4e8eb] bg-[#fafbfb] px-3 py-2.5">

            <span className="text-[8px] font-semibold uppercase tracking-[0.1em] text-[#929ca5]">
              Backend
            </span>

            <div className="flex items-center gap-1.5">

              <span className="h-1.5 w-1.5 rounded-full bg-[#16875d]" />

              <span className="text-[8px] font-bold uppercase tracking-[0.05em] text-[#16875d]">
                Online
              </span>

            </div>

          </div>

        </div>

      </div>

    </aside>
  );
}