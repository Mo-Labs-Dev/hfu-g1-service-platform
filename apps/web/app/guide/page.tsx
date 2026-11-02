import NavigationPanel from "@/components/navigation/NavigationPanel";

export default function GuidePage() {
  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1600px] px-6 py-10 md:px-10 lg:px-16 lg:py-14">
          <div className="h-[3px] w-12 bg-[#009b77]" />

          <p className="mt-6 text-[10px] font-bold uppercase tracking-[0.22em] text-[#8a9499]">
            G1 Engineering Environment
          </p>

          <h1 className="mt-5 text-[40px] font-bold tracking-[-0.04em] text-[#2d3337]">
            Lab Guide
          </h1>

          <p className="mt-4 max-w-2xl text-[14px] leading-6 text-[#707b81]">
            Configure and test the visitor guidance
            experience for the Unitree G1 humanoid robot.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-[1600px] px-6 py-10 md:px-10 lg:px-16">
        <div className="max-w-5xl">
          <NavigationPanel />
        </div>
      </section>
    </div>
  );
}