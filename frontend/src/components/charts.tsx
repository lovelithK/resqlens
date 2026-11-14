// Lightweight, dependency-free SVG charts (bar, donut, gauge, line).
import { useState } from "react";
import { scoreColor } from "../lib/format";

const AXIS = "#4f6080";
const GRID = "#1c2a43";

export function Gauge({ value, size = 150, label, sub }: { value: number | null | undefined; size?: number; label?: string; sub?: string }) {
  const r = size / 2 - 12;
  const c = 2 * Math.PI * r;
  const v = value ?? 0;
  const color = scoreColor(value);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="score-ring" role="img" aria-label={`${label || "score"} ${value ?? "n/a"}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1a2a44" strokeWidth={10} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round"
        strokeDasharray={`${(c * Math.max(0, Math.min(100, v))) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray .5s ease" }} />
      <text x="50%" y="48%" textAnchor="middle" fill="#e5ecf6" fontSize={size / 4.6} fontWeight={650}>{value ?? "–"}</text>
      {label && <text x="50%" y="66%" textAnchor="middle" fill="#7d8ea9" fontSize={11.5}>{label}</text>}
      {sub && <text x="50%" y="78%" textAnchor="middle" fill={color} fontSize={12} fontWeight={600}>{sub}</text>}
    </svg>
  );
}

export function Donut({ data, size = 150, center }: { data: { label: string; value: number; color: string }[]; size?: number; center?: string }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = size / 2 - 14;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="row" style={{ gap: 18, alignItems: "center", flexWrap: "wrap" }}>
      <svg width={size} height={size} role="img" aria-label="distribution chart">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1a2a44" strokeWidth={16} />
        {total > 0 && data.filter((d) => d.value > 0).map((d) => {
          const len = (d.value / total) * c;
          const el = <circle key={d.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={d.color} strokeWidth={16}
            strokeDasharray={`${Math.max(0, len - 2)} ${c}`} strokeDashoffset={-offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} />;
          offset += len;
          return el;
        })}
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fill="#e5ecf6" fontSize={22} fontWeight={650}>{center ?? total}</text>
      </svg>
      <div className="col" style={{ gap: 6 }}>
        {data.map((d) => (
          <div key={d.label} className="row small" style={{ gap: 8 }}>
            <span className="legend-dot" style={{ background: d.color }} /><span className="muted" style={{ minWidth: 90 }}>{d.label}</span>
            <span className="num strong">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BarChart({ data, height = 200, unit = "", horizontal = false, max }: {
  data: { label: string; value: number; color?: string; note?: string }[]; height?: number; unit?: string; horizontal?: boolean; max?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const top = max ?? Math.max(1, ...data.map((d) => d.value));
  if (horizontal) {
    return (
      <div className="col" style={{ gap: 8 }}>
        {data.map((d, i) => (
          <div key={i}>
            <div className="row small" style={{ justifyContent: "space-between" }}>
              <span className="muted ellipsis">{d.label}</span><span className="num strong">{Math.round(d.value * 10) / 10}{unit}</span>
            </div>
            <div className="factor-bar mt8" style={{ marginTop: 4 }}><div style={{ width: `${(d.value / top) * 100}%`, background: d.color || "var(--accent)" }} /></div>
          </div>
        ))}
      </div>
    );
  }
  const w = Math.max(320, data.length * 90);
  const pad = { l: 36, r: 10, t: 14, b: 42 };
  const ih = height - pad.t - pad.b;
  const bw = Math.min(46, ((w - pad.l - pad.r) / data.length) * 0.55);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * top);
  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label="bar chart" preserveAspectRatio="xMidYMid meet">
      {ticks.map((t, i) => {
        const y = pad.t + ih - (t / top) * ih;
        return <g key={i}><line x1={pad.l} x2={w - pad.r} y1={y} y2={y} stroke={GRID} /><text x={pad.l - 6} y={y + 4} textAnchor="end" fill={AXIS} fontSize={10}>{Math.round(t)}</text></g>;
      })}
      {data.map((d, i) => {
        const slot = (w - pad.l - pad.r) / data.length;
        const x = pad.l + slot * i + slot / 2 - bw / 2;
        const h = (d.value / top) * ih;
        const maxChars = Math.max(6, Math.floor(slot / 6.2));
        return (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <rect x={x} y={pad.t + ih - h} width={bw} height={Math.max(0, h)} rx={4} fill={d.color || "#3b82f6"} opacity={hover === null || hover === i ? 1 : 0.55} />
            <text x={x + bw / 2} y={pad.t + ih - h - 5} textAnchor="middle" fill="#b6c3d8" fontSize={11} fontWeight={600}>{Math.round(d.value * 10) / 10}{unit}</text>
            <text x={x + bw / 2} y={height - pad.b + 16} textAnchor="middle" fill="#7d8ea9" fontSize={10.5}>{d.label.length > maxChars ? d.label.slice(0, maxChars - 1) + "…" : d.label}</text>
            {d.note && <text x={x + bw / 2} y={height - pad.b + 30} textAnchor="middle" fill={AXIS} fontSize={9.5}>{d.note}</text>}
          </g>
        );
      })}
    </svg>
  );
}

export function LineChart({ series, height = 200, yMax, xLabel, step = false }: {
  series: { name: string; color: string; points: { x: number; y: number }[] }[]; height?: number; yMax?: number; xLabel?: string; step?: boolean;
}) {
  const all = series.flatMap((s) => s.points);
  if (!all.length) return <div className="muted small">No data yet</div>;
  const w = 560;
  const pad = { l: 34, r: 12, t: 12, b: 30 };
  const xMax = Math.max(1, ...all.map((p) => p.x));
  const top = yMax ?? Math.max(1, ...all.map((p) => p.y));
  const sx = (x: number) => pad.l + (x / xMax) * (w - pad.l - pad.r);
  const sy = (y: number) => pad.t + (1 - y / top) * (height - pad.t - pad.b);
  const path = (pts: { x: number; y: number }[]) => pts.map((p, i) => {
    if (i === 0) return `M${sx(p.x)},${sy(p.y)}`;
    return step ? `H${sx(p.x)}V${sy(p.y)}` : `L${sx(p.x)},${sy(p.y)}`;
  }).join("");
  return (
    <div>
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label="line chart">
        {[0, 0.5, 1].map((t) => <g key={t}><line x1={pad.l} x2={w - pad.r} y1={sy(t * top)} y2={sy(t * top)} stroke={GRID} /><text x={pad.l - 6} y={sy(t * top) + 4} fill={AXIS} fontSize={10} textAnchor="end">{Math.round(t * top)}</text></g>)}
        <text x={w - pad.r} y={height - 6} fill={AXIS} fontSize={10} textAnchor="end">{xLabel ? `${xLabel} (max ${Math.round(xMax * 10) / 10})` : ""}</text>
        {series.map((s) => <g key={s.name}>
          <path d={path(s.points)} fill="none" stroke={s.color} strokeWidth={2} />
          {s.points.map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.6} fill={s.color} />)}
        </g>)}
      </svg>
      {series.length > 1 && <div className="row wrap small" style={{ gap: 14 }}>{series.map((s) => <span key={s.name} className="row" style={{ gap: 6 }}><span className="legend-dot" style={{ background: s.color }} /><span className="muted">{s.name}</span></span>)}</div>}
    </div>
  );
}
