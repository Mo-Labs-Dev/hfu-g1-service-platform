import StudioHeader from "@/components/layout/StudioHeader";

export default function StudioLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="min-h-screen bg-white">

      <StudioHeader />

      <main>
        {children}
      </main>

    </div>
  );
}