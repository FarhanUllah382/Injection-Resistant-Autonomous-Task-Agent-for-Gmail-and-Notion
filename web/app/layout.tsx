import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Inbox-to-Action — Review",
  description: "Review Gmail task candidates before they go to Notion",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
