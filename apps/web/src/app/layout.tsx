import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Search Pal",
  description:
    "Your loyal corporate companion for navigating the job-search experience.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-corp-bg text-corp-text">{children}</body>
    </html>
  );
}
