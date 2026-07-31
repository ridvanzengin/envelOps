// Auto-compact stat-tile values (1,284 / 12.9K / 4.2M) per the dataviz
// skill's figure contract -- this app's numbers stay small (a portfolio
// project's seeded/calibration data, not real traffic), but the format
// should still hold up if that ever changes.
export function formatCompactNumber(value: number): string {
  if (value < 1000) return value.toLocaleString();
  if (value < 1_000_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}
