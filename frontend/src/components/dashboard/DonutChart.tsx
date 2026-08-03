interface IntentBreakdownItem {
  intent: string;
  count: number;
  percentage: number;
}

const SIZE = 232;
const STROKE = 38;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// 2px surface gap between segments (dataviz skill's mark spec) --
// converted from px to an arc-length subtracted off each segment's dash.
const GAP = 2;

// Purchase intent and complaint/problem reuse the exact same tokens
// DiagnosticsBadges.tsx already uses for these two intents (--accent,
// --info) -- direct instruction, so this donut reads as the same
// category everywhere it appears in the app (rail badges, filter chips,
// this chart), not a second, differently-colored encoding of the same
// data. knowledge_question/small_talk/other have no existing badge
// color (DiagnosticsBadges leaves them the neutral default), so those
// three keep the dedicated chart palette from the dataviz skill's
// reference instance (slots 3-5: aqua/yellow/magenta) -- validated
// against this exact fixed order, including adjacency to --accent/
// --info and the donut's circular wraparound back to --accent, in both
// light and dark mode, before use. One caveat found and accepted, not
// unsafe: --accent's own light-mode step sits just under the palette's
// chroma floor (0.091 vs 0.10) and its dark-mode step sits above the
// lightness band -- both cosmetic (this hue reads slightly washed-out/
// bright next to its neighbors), not a CVD-separation failure, which is
// the check that actually matters for telling segments apart.
const INTENT_COLOR_VARS: Record<string, string> = {
  purchase_intent: "var(--accent)",
  complaint_or_problem: "var(--info)",
  knowledge_question: "var(--dashboard-chart-3)",
  small_talk: "var(--dashboard-chart-4)",
  other: "var(--dashboard-chart-5)",
};
const FALLBACK_COLOR_VAR = "var(--dashboard-chart-3)";

// Light-mode aqua/yellow/magenta sit below 3:1 contrast against the
// surface (the palette's own documented trade-off) -- the legend's
// direct labels are the required relief channel, not optional polish,
// so identity never rides on the fill color alone.
export function DonutChart({
  items,
  labelFor,
}: {
  items: IntentBreakdownItem[];
  labelFor: (intent: string) => string;
}) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  let cumulative = 0;

  return (
    <div className="dashboard-donut">
      <div className="dashboard-donut__chart">
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="dashboard-donut__svg"
          role="img"
          aria-label="Conversations by intent"
        >
          <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
            {items.map((item) => {
              const dash = Math.max((item.percentage / 100) * CIRCUMFERENCE - GAP, 0);
              const offset = -cumulative;
              cumulative += (item.percentage / 100) * CIRCUMFERENCE;
              return (
                <circle
                  key={item.intent}
                  cx={SIZE / 2}
                  cy={SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  stroke={INTENT_COLOR_VARS[item.intent] ?? FALLBACK_COLOR_VAR}
                  strokeWidth={STROKE}
                  strokeLinecap="round"
                  strokeDasharray={`${dash} ${CIRCUMFERENCE - dash}`}
                  strokeDashoffset={offset}
                />
              );
            })}
          </g>
        </svg>
        <div className="dashboard-donut__center">
          <span className="dashboard-donut__center-value">{total}</span>
          <span className="dashboard-donut__center-label">Total</span>
        </div>
      </div>
      <ul className="dashboard-donut__legend">
        {items.map((item) => (
          <li key={item.intent} className="dashboard-donut__legend-row">
            <span
              className="dashboard-donut__legend-dot"
              style={{ background: INTENT_COLOR_VARS[item.intent] ?? FALLBACK_COLOR_VAR }}
              aria-hidden="true"
            />
            <span className="dashboard-donut__legend-label">{labelFor(item.intent)}</span>
            <span className="dashboard-donut__legend-value">
              {item.percentage}%{" "}
              <span className="dashboard-donut__legend-count">({item.count})</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
