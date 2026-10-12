
import Link from "next/link";

type HeaderProps = {
  title?: string;
  description?: string;
};

export default function Header({
  title,
  description,
}: HeaderProps) {
  return (
    <>
      <header className="relative z-50 h-[78px] w-full border-b border-[#c3c6c4] bg-[#d7d8d6]">
        <div className="mx-auto flex h-full w-full max-w-[1700px] items-center px-8">

          {/* LEFT */}
          <div className="flex h-full items-center">

            <Link
              href="/"
              className="flex shrink-0 items-center"
            >
              <img
                src="/hfu-logo.svg"
                alt="Hochschule Furtwangen University"
                className="h-[56px] w-auto"
              />
            </Link>

            <div className="mx-6 h-[50px] w-px bg-[#b5b9b7]" />

            <div className="flex flex-col justify-center">

              <Link
                href="/"
                className="text-[25px] font-bold leading-none tracking-[-0.04em] text-[#292f33]"
              >
                G1 Studio
              </Link>

              <p className="mt-2 text-[10px] font-medium text-[#657078]">
                Institut für Produkt und Service Engineering
              </p>

            </div>

          </div>

          {/* RIGHT */}
          <div className="ml-auto flex h-full items-center">

            {/* ROBOT MODEL */}
            <div className="flex h-full items-center px-8">
              <span className="text-[15px] font-bold text-[#292f33]">
                Unitree G1
              </span>
            </div>

            {/* ROBOT */}
            <Link
              href="/studio"
              className="
                group
                relative
                flex
                h-full
                items-center
                px-8
                text-[15px]
                font-bold
                text-[#292f33]
                transition-colors
                duration-200
                hover:text-[#009b77]
              "
            >
              Robot

              <span
                className="
                  absolute
                  bottom-0
                  left-8
                  right-8
                  h-[3px]
                  bg-[#009b77]
                  opacity-0
                  transition-opacity
                  duration-200
                  group-hover:opacity-100
                "
              />
            </Link>

            {/* USER */}
            <div className="ml-2 flex h-full items-center border-l border-[#b9bdbb] pl-7">

              <button
                type="button"
                className="group flex items-center gap-4"
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

                <span className="text-[10px] text-[#4e575c]">
                  ▼
                </span>
              </button>

            </div>

          </div>

        </div>
      </header>

      {(title || description) && (
        <div className="border-b border-slate-800 bg-slate-950 px-8 py-7">
          <div className="mx-auto max-w-[1600px]">
            {title && (
              <h1 className="text-3xl font-bold text-white">
                {title}
              </h1>
            )}

            {description && (
              <p className="mt-2 text-sm text-slate-400">
                {description}
              </p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
