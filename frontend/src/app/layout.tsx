import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { AuthGate } from "@/components/AuthGate";
import { NavBar } from "@/components/NavBar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "Time Tracking & Tasks",
  description: "Kanban board with per-task time tracking",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans antialiased">
        <AuthGate>
          <NavBar />
          {children}
        </AuthGate>
      </body>
    </html>
  );
}
