// A stat tile's trend figure (dataviz skill: "trend (optional; sparkline
// ... current period in the accent)"). No axes/tooltip/legend -- a
// sparkline is a glance-only shape, not a chart someone reads values off
// of; the tile's own value + delta already carry the precise numbers.
export function Sparkline({ values, color }: { values: number[]; color: string }) {
  const width = 72;
  const height = 24;
  const max = Math.max(...values, 1);
  const stepX = values.length > 1 ? width / (values.length - 1) : 0;

  // A single value (the "1 day" range) has no line to draw between -- a
  // 1-point polyline renders no visible segment at all, which read as
  // the sparkline vanishing rather than a deliberate one-point view. A
  // centered dot is the only meaningful way to show it.
  if (values.length === 1) {
    const y = height - (values[0] / max) * height;
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        aria-hidden="true"
        className="dashboard-sparkline"
      >
        <circle cx={width / 2} cy={y} r={2.5} fill={color} />
      </svg>
    );
  }

  const points = values
    .map((value, i) => {
      const x = i * stepX;
      const y = height - (value / max) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      className="dashboard-sparkline"
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
