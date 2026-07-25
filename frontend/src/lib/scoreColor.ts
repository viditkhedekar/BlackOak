// Map a 0–100 score to a heat color: red (low) → amber (mid) → green (high).
// Returns an rgba background tuned for the dark terminal surface.
export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "transparent";
  const s = Math.max(0, Math.min(100, score));
  // 0 -> hue 0 (red), 50 -> 45 (amber), 100 -> 140 (green)
  const hue = s <= 50 ? (s / 50) * 45 : 45 + ((s - 50) / 50) * 95;
  return `hsla(${hue}, 65%, 45%, 0.22)`;
}

export function scoreText(score: number | null | undefined): string {
  if (score == null) return "var(--muted)";
  const s = Math.max(0, Math.min(100, score));
  const hue = s <= 50 ? (s / 50) * 45 : 45 + ((s - 50) / 50) * 95;
  return `hsl(${hue}, 70%, 70%)`;
}
