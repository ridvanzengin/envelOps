interface IntentBreakdownItem {
  intent: string;
  count: number;
  percentage: number;
}

// "Conversations by intent" -- a ranked horizontal bar list, not a donut.
// Two reasons, both from the dataviz skill loaded for this build: (1)
// part-to-whole "rides on the stacked bar chart; donut stays
// deprioritized" by default, and (2) this app's only existing color
// tokens are status colors (accent/success/warning/danger/info), and
// running the six-checks validator on them as a 5-slot categorical
// palette hard-FAILs CVD separation (danger<->success ~2.2 under
// deuteranopia -- the colors were never designed to sit side by side as
// identity). A single-hue ranked list sidesteps needing a categorical
// palette at all: identity comes from the row's own label text, not from
// telling colors apart (dataviz skill: "identity is never color-alone").
export function IntentBarList({
  items,
  labelFor,
}: {
  items: IntentBreakdownItem[];
  labelFor: (intent: string) => string;
}) {
  const maxPercentage = Math.max(...items.map((i) => i.percentage), 1);

  return (
    <ul className="dashboard-bar-list">
      {items.map((item) => (
        <li key={item.intent} className="dashboard-bar-list__row">
          <span className="dashboard-bar-list__label">{labelFor(item.intent)}</span>
          <div className="dashboard-bar-list__track">
            <div
              className="dashboard-bar-list__bar"
              style={{ width: `${(item.percentage / maxPercentage) * 100}%` }}
            />
          </div>
          <span className="dashboard-bar-list__value">
            {item.percentage}% <span className="dashboard-bar-list__count">({item.count})</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
