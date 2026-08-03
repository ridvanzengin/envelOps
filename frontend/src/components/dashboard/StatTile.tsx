import type { ReactNode } from "react";

import { formatCompactNumber } from "../../utils/formatNumber";
import { Sparkline } from "./Sparkline";

interface StatTileProps {
  label: string;
  // null renders as "--" with no delta/sparkline -- e.g. avg response
  // time when no inbound message in range was ever answered yet.
  value: number | null;
  formatValue?: (value: number) => string;
  // Omit both to render a bare value with no delta -- avg response time
  // has no comparable previous-period figure computed server-side, so it
  // renders as a plain stat, same as the dataviz skill's "delta
  // (optional)" figure contract.
  prevValue?: number;
  // Which direction of change is the good one for this specific metric --
  // more conversations/leads is good, more escalations is not. Delta
  // color follows this, not a blanket "up = green."
  increaseIsGood?: boolean;
  sparklineValues?: number[];
  icon?: ReactNode;
}

export function StatTile({
  label,
  value,
  formatValue = formatCompactNumber,
  prevValue,
  increaseIsGood = true,
  sparklineValues,
  icon,
}: StatTileProps) {
  const delta =
    value === null || prevValue === undefined ? null : computeDelta(value, prevValue, increaseIsGood);

  return (
    <div className="card dashboard-stat-tile">
      <div className="dashboard-stat-tile__header">
        {icon && <span className="dashboard-stat-tile__icon">{icon}</span>}
        <span className="dashboard-stat-tile__label">{label}</span>
      </div>
      <div className="dashboard-stat-tile__value">{value === null ? "—" : formatValue(value)}</div>
      <div className="dashboard-stat-tile__footer">
        {delta && (
          <span className={`dashboard-stat-tile__delta dashboard-stat-tile__delta--${delta.tone}`}>
            {delta.text}
          </span>
        )}
        {value !== null && sparklineValues && sparklineValues.length > 1 && (
          <Sparkline values={sparklineValues} color="var(--accent)" />
        )}
      </div>
    </div>
  );
}

function computeDelta(
  value: number,
  prevValue: number,
  increaseIsGood: boolean,
): { text: string; tone: "positive" | "negative" | "neutral" } | null {
  if (value === prevValue) {
    return { text: "No change", tone: "neutral" };
  }
  const isIncrease = value > prevValue;
  const tone: "positive" | "negative" = isIncrease === increaseIsGood ? "positive" : "negative";
  const arrow = isIncrease ? "↗" : "↘";
  if (prevValue === 0) {
    return { text: `${arrow} New`, tone };
  }
  const percent = Math.abs(((value - prevValue) / prevValue) * 100);
  return { text: `${arrow} ${percent.toFixed(1)}%`, tone };
}
