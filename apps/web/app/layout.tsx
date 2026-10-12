import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "G1 Studio",
  description: "Engineering platform for the Unitree G1 humanoid robot",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="m-0 bg-white">{children}</body>
    </html>
  );
}