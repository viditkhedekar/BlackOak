"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { label: "Command Center", href: "/", ready: true },
  { label: "Rankings", href: "/rankings", ready: true },
  { label: "Decision Journal", href: "/journal", ready: true },
  { label: "Research", href: "/research", ready: true },
  { label: "Backtest Lab", href: "/backtests", ready: true },
  { label: "System Health", href: "/system", ready: true },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center gap-2 px-5 py-5">
        <span className="font-mono text-lg font-bold tracking-tight text-accent">◆ BLACKOAK</span>
      </div>
      <nav className="flex flex-col gap-0.5 px-2">
        {NAV.map((item) =>
          item.ready ? (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded px-3 py-2 text-sm ${
                pathname === item.href
                  ? "bg-line text-foreground"
                  : "text-muted hover:bg-line/50 hover:text-foreground"
              }`}
            >
              {item.label}
            </Link>
          ) : (
            <span
              key={item.href}
              className="cursor-not-allowed rounded px-3 py-2 text-sm text-muted/50"
              title="Coming in a later phase"
            >
              {item.label}
            </span>
          ),
        )}
      </nav>
      <div className="mt-auto px-5 py-4 font-mono text-[10px] text-muted">
        PAPER TRADING ONLY
      </div>
    </aside>
  );
}
