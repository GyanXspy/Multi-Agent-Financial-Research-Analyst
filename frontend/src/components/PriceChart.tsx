/**
 * PriceChart — dependency-free SVG area chart for the 1-year weekly price history.
 * Gradient fill, min/max annotations, and pointer-tracked tooltip.
 */

import { useMemo, useRef, useState } from 'react';

interface PriceChartProps {
  prices: number[];
  dates?: string[];
  currency?: string;
}

const W = 800;
const H = 220;
const PAD = { top: 16, right: 12, bottom: 24, left: 12 };

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' });
}

export default function PriceChart({ prices, dates = [], currency = 'USD' }: PriceChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const geom = useMemo(() => {
    if (prices.length < 2) return null;
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const span = max - min || 1;
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;

    const pts = prices.map((p, i) => ({
      x: PAD.left + (i / (prices.length - 1)) * innerW,
      y: PAD.top + (1 - (p - min) / span) * innerH,
    }));

    const line = pts.map((pt, i) => `${i === 0 ? 'M' : 'L'}${pt.x.toFixed(1)},${pt.y.toFixed(1)}`).join(' ');
    const area = `${line} L${pts[pts.length - 1].x.toFixed(1)},${H - PAD.bottom} L${PAD.left},${H - PAD.bottom} Z`;

    return { pts, line, area, min, max };
  }, [prices]);

  if (!geom) return null;

  const first = prices[0];
  const last = prices[prices.length - 1];
  const changePct = ((last - first) / first) * 100;
  const up = changePct >= 0;
  const strokeColor = up ? 'var(--color-emerald-400)' : 'var(--color-rose-400)';
  const symbol = currency === 'INR' ? '₹' : '$';

  const handleMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * W;
    const idx = Math.round(((relX - PAD.left) / (W - PAD.left - PAD.right)) * (prices.length - 1));
    setHoverIdx(Math.max(0, Math.min(prices.length - 1, idx)));
  };

  const hover = hoverIdx != null ? geom.pts[hoverIdx] : null;

  return (
    <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 shadow-lg animate-fade-in">
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-400">
          Price History · 1 Year
        </h3>
        <span className={`text-sm font-bold tabular-nums ${up ? 'text-emerald-300' : 'text-rose-300'}`}>
          {up ? '▲' : '▼'} {Math.abs(changePct).toFixed(1)}%
        </span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto select-none"
        role="img"
        aria-label={`One-year price chart. Started at ${symbol}${first.toFixed(2)}, currently ${symbol}${last.toFixed(2)}, ${up ? 'up' : 'down'} ${Math.abs(changePct).toFixed(1)} percent.`}
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.25" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Area + line */}
        <path d={geom.area} fill="url(#chart-fill)" />
        <path d={geom.line} fill="none" stroke={strokeColor} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* Hover crosshair */}
        {hover && (
          <g>
            <line x1={hover.x} y1={PAD.top} x2={hover.x} y2={H - PAD.bottom} stroke="var(--color-ink-600)" strokeWidth="1" strokeDasharray="3 3" />
            <circle cx={hover.x} cy={hover.y} r="4" fill={strokeColor} stroke="var(--color-ink-950)" strokeWidth="2" />
          </g>
        )}
      </svg>

      <div className="flex justify-between items-center mt-2 text-xs text-ink-400 tabular-nums">
        {hoverIdx != null ? (
          <>
            <span>{dates[hoverIdx] ? formatDate(dates[hoverIdx]) : `Week ${hoverIdx + 1}`}</span>
            <span className="font-semibold text-white">{symbol}{prices[hoverIdx].toFixed(2)}</span>
          </>
        ) : (
          <>
            <span>Low {symbol}{geom.min.toFixed(2)}</span>
            <span>High {symbol}{geom.max.toFixed(2)}</span>
          </>
        )}
      </div>
    </div>
  );
}
