interface IntentBreakdownItem {
  intent: string;
  count: number;
  percentage: number;
}

const SIZE = 176;
const STROKE = 30;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// 2px surface gap between segments (dataviz skill's mark spec) --
// converted from px to an arc-length subtracted off each segment's dash.
const GAP = 2;

// Fixed slot order, one per app/pipeline/graph.py's five detected_intent
// values -- these five CSS custom properties (Dashboard.css) are a
// dedicated categorical palette, deliberately NOT this app's existing
// --accent/--success/--warning/--danger/--info tokens. Running the
// dataviz skill's six-checks validator on those five status tokens as a
// categorical set hard-FAILs CVD separation (danger<->success ΔE ~2.2
// under deuteranopia -- they were only ever designed to be used one at a
// time, paired with an icon+label, never side by side as series
// identity). These five hues instead come from the skill's own
// documented reference palette (slots 1-5: blue/orange/aqua/yellow/
// magenta) -- validated directly against this exact fixed order,
// including the donut's circular wraparound pair (slot 5 back to slot
// 1), in both light and dark mode, before use.
const SEGMENT_COLOR_VARS = [
  "var(--dashboard-chart-1)",
  "var(--dashboard-chart-2)",
  "var(--dashboard-chart-3)",
  "var(--dashboard-chart-4)",
  "var(--dashboard-chart-5)",
];

// Light-mode slots 3/4/5 sit below 3:1 contrast against the surface (the
// palette's own documented trade-off) -- the legend's direct labels are
// the required relief channel, not optional polish, so identity never
// rides on the fill color alone.
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
            {items.map((item, i) => {
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
                  stroke={SEGMENT_COLOR_VARS[i % SEGMENT_COLOR_VARS.length]}
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
        {items.map((item, i) => (
          <li key={item.intent} className="dashboard-donut__legend-row">
            <span
              className="dashboard-donut__legend-dot"
              style={{ background: SEGMENT_COLOR_VARS[i % SEGMENT_COLOR_VARS.length] }}
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
