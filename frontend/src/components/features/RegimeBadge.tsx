"use client";

const COLORS: Record<string, string> = {
  risk_on: "hsl(140,60%,45%)",
  neutral: "hsl(45,70%,50%)",
  risk_off: "hsl(0,65%,52%)",
};

export function RegimeBadge({ label }: { label: string | null | undefined }) {
  if (!label) return <span className="text-muted">—</span>;
  const color = COLORS[label] ?? "var(--muted)";
  return (
    <span
      className="rounded px-2 py-0.5 font-mono text-xs font-semibold uppercase tracking-wide"
      style={{ backgroundColor: `${color}22`, color }}
    >
      {label.replace("_", "-")}
    </span>
  );
}
