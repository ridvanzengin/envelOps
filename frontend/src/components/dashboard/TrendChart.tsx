import { useLayoutEffect, useMemo, useRef, useState } from "react";

interface TrendPoint {
  date: string;
  count: number;
}

const HEIGHT = 220;
const PADDING = { top: 16, right: 16, bottom: 28, left: 40 };
// Only used for the very first render, before the ResizeObserver below
// has measured the real container -- close to a typical half-row card
// width so there's no visible jump once the real value lands.
const FALLBACK_WIDTH = 560;

function niceMax(value: number): number {
  if (value <= 0) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

// "Conversations over time" -- the one full-size chart on the page. Line +
// soft area wash (dataviz skill: single series needs no legend, hairline
// recessive grid, crosshair+tooltip hover, an sr-only table twin so the
// data isn't color/hover-only).
//
// The SVG's viewBox tracks the container's *real* pixel width via
// ResizeObserver, rather than staying at one fixed width and letting CSS
// (width:100%) scale it down to fit a narrower card. That original
// approach scaled the whole coordinate system, including things
// specified as plain numbers inside the SVG -- stroke widths, dot radii,
// and (worst of all) text font-size, which has no CSS-pixel floor the
// way HTML text does. On a narrower card (small-screen layout, not yet
// mobile) an "11px" axis label was actually rendering at ~5 real pixels,
// found live. Keeping the viewBox's width equal to the actual rendered
// width makes the scale factor exactly 1, so every mark spec (2px line,
// 11px tick labels) stays true to its real pixel size regardless of how
// narrow the card gets -- only the plotted width (point spacing)
// adapts, height stays fixed.
export function TrendChart({
  points,
  formatDate,
}: {
  points: TrendPoint[];
  formatDate: (isoDate: string) => string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width;
      if (measured && measured > 0) setWidth(measured);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const plotWidth = width - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const maxValue = useMemo(() => niceMax(Math.max(...points.map((p) => p.count), 0)), [points]);
  const stepX = points.length > 1 ? plotWidth / (points.length - 1) : 0;

  function xFor(i: number): number {
    return PADDING.left + i * stepX;
  }
  function yFor(count: number): number {
    return PADDING.top + plotHeight - (count / maxValue) * plotHeight;
  }

  const linePoints = points.map((p, i) => `${xFor(i)},${yFor(p.count)}`).join(" ");
  const areaPoints = `${xFor(0)},${yFor(0)} ${linePoints} ${xFor(points.length - 1)},${yFor(0)}`;

  const yTicks = [0, maxValue / 2, maxValue];
  // Thin out x-axis labels so they never collide -- roughly one label
  // per 80px of real plotted width, regardless of a 7/30/90-day range or
  // how narrow the card is.
  const targetLabelCount = Math.max(2, Math.floor(plotWidth / 80));
  const labelEvery = Math.max(1, Math.ceil(points.length / targetLabelCount));

  function handleMove(event: React.PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = ((event.clientX - rect.left) / rect.width) * width;
    const index = Math.round((relativeX - PADDING.left) / (stepX || 1));
    setHoverIndex(Math.min(Math.max(index, 0), points.length - 1));
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  return (
    <div className="dashboard-trend-chart" ref={containerRef}>
      <svg
        viewBox={`0 0 ${width} ${HEIGHT}`}
        width={width}
        height={HEIGHT}
        className="dashboard-trend-chart__svg"
        role="img"
        aria-label="Conversations over time"
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={PADDING.left}
              x2={width - PADDING.right}
              y1={yFor(tick)}
              y2={yFor(tick)}
              className="dashboard-trend-chart__gridline"
            />
            <text x={PADDING.left - 8} y={yFor(tick)} className="dashboard-trend-chart__tick" textAnchor="end" dy="0.32em">
              {Math.round(tick).toLocaleString()}
            </text>
          </g>
        ))}

        {points.map((p, i) =>
          i % labelEvery === 0 ? (
            <text
              key={p.date}
              x={xFor(i)}
              y={HEIGHT - 8}
              className="dashboard-trend-chart__tick"
              textAnchor="middle"
            >
              {formatDate(p.date)}
            </text>
          ) : null,
        )}

        <polygon points={areaPoints} className="dashboard-trend-chart__area" />
        <polyline points={linePoints} className="dashboard-trend-chart__line" />

        {hoverIndex !== null && (
          <line
            x1={xFor(hoverIndex)}
            x2={xFor(hoverIndex)}
            y1={PADDING.top}
            y2={PADDING.top + plotHeight}
            className="dashboard-trend-chart__crosshair"
          />
        )}
        {hoverIndex !== null && (
          <circle
            cx={xFor(hoverIndex)}
            cy={yFor(points[hoverIndex].count)}
            r={4}
            className="dashboard-trend-chart__dot"
          />
        )}
      </svg>

      {hovered && (
        <div
          className="dashboard-trend-chart__tooltip"
          style={{ left: `${(xFor(hoverIndex ?? 0) / width) * 100}%` }}
        >
          <strong>{hovered.count.toLocaleString()}</strong>
          <span>{formatDate(hovered.date)}</span>
        </div>
      )}

      {/* Wrapped in a plain div, not applied to the table itself -- a
          table's own intrinsic content-based sizing ignores a tiny
          explicit width/height (unlike a div), so at a 90-day range
          this rendered at full size and inflated the page's scrollable
          area instead of actually being clipped to 1x1. Found live. */}
      <div className="sr-only">
        <table>
          <caption>Conversations per day</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Conversations</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.date}>
                <td>{p.date}</td>
                <td>{p.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
