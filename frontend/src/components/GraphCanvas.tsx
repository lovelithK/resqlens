// Interactive SVG dependency graph: zoom / pan / drag / connect / auto-layout,
// status colouring and failure-propagation highlighting.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPE, type WheelEvent } from "react";
import { LuLayoutDashboard, LuMaximize, LuZoomIn, LuZoomOut } from "react-icons/lu";
import { autoLayout, NODE_H, NODE_W } from "../lib/layout";
import { IMPACT_COLOR, STATUS_COLOR, TYPE_LABEL } from "../lib/format";
import { TypeIcon } from "./ui";

export type GNode = {
  id: number; name: string; component_type: string; status: string; health: number; criticality: string;
  pos_x?: number | null; pos_y?: number | null;
};
export type GEdge = {
  id: number; source_component_id: number; target_component_id: number; dependency_type: string;
  fallback_component_id?: number | null;
};
type Pos = Record<number, { x: number; y: number }>;

const layoutEdges = (edges: GEdge[]) => edges.flatMap((e) => [
  { source: e.source_component_id, target: e.target_component_id },
  ...(e.fallback_component_id ? [{ source: e.source_component_id, target: e.fallback_component_id }] : []),
]);

type Props = {
  nodes: GNode[];
  edges: GEdge[];
  impact?: Record<number, string>;
  propagationEdges?: { from: number; to: number }[];
  focusIds?: Set<number> | null;
  badges?: Record<number, string>;
  selectedId?: number | null;
  selectedEdgeId?: number | null;
  onSelectNode?: (id: number | null) => void;
  onSelectEdge?: (id: number | null) => void;
  editable?: boolean;
  onConnect?: (source: number, target: number) => void;
  onPositionsChange?: (pos: Pos) => void;
  hint?: string;
  showLegend?: boolean;
};

export default function GraphCanvas(p: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [pos, setPos] = useState<Pos>({});
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [drag, setDrag] = useState<null | { kind: "pan" | "node" | "connect"; id?: number; sx: number; sy: number; ox: number; oy: number; moved?: boolean }>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [hoverTarget, setHoverTarget] = useState<number | null>(null);
  const [hintVisible, setHintVisible] = useState(true);
  const nodeKey = p.nodes.map((n) => n.id).join(",");
  const fitted = useRef("");

  // initialise positions from persisted coordinates, auto-layout if any are missing
  useEffect(() => {
    setPos((prev) => {
      const missing = p.nodes.some((n) => (n.pos_x === null || n.pos_x === undefined) && !prev[n.id]);
      if (missing) {
        const layout = autoLayout(p.nodes, layoutEdges(p.edges));
        const merged: Pos = {};
        p.nodes.forEach((n) => {
          merged[n.id] = prev[n.id] || (n.pos_x !== null && n.pos_x !== undefined ? { x: n.pos_x, y: n.pos_y as number } : layout[n.id]);
        });
        if (p.nodes.every((n) => n.pos_x === null || n.pos_x === undefined)) {
          Object.assign(merged, layout);
          p.onPositionsChange?.(layout);
        } else p.onPositionsChange?.(merged);
        return merged;
      }
      const next: Pos = {};
      p.nodes.forEach((n) => { next[n.id] = prev[n.id] || { x: n.pos_x as number, y: n.pos_y as number }; });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeKey]);

  const fit = useCallback(() => {
    const svg = svgRef.current;
    const ids = Object.keys(pos);
    if (!svg || !ids.length) return;
    const xs = ids.map((i) => pos[+i].x), ys = ids.map((i) => pos[+i].y);
    const minX = Math.min(...xs) - 30, maxX = Math.max(...xs) + NODE_W + 30;
    const minY = Math.min(...ys) - 34, maxY = Math.max(...ys) + NODE_H + 96;
    const { width, height } = svg.getBoundingClientRect();
    if (!width || !height) return;
    const k = Math.min(1.25, Math.max(0.25, Math.min(width / (maxX - minX), height / (maxY - minY))));
    setView({ k, x: (width - (maxX - minX) * k) / 2 - minX * k, y: (height - (maxY - minY) * k) / 2 - minY * k });
  }, [pos]);

  useEffect(() => {
    if (Object.keys(pos).length && fitted.current !== nodeKey) {
      fitted.current = nodeKey;
      requestAnimationFrame(fit);
    }
  }, [pos, nodeKey, fit]);

  const toWorld = (cx: number, cy: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: (cx - r.left - view.x) / view.k, y: (cy - r.top - view.y) / view.k };
  };

  const onWheel = (e: WheelEvent<SVGSVGElement>) => {
    const r = svgRef.current!.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const k = Math.min(2.2, Math.max(0.2, view.k * (e.deltaY < 0 ? 1.1 : 0.9)));
    setView({ k, x: mx - ((mx - view.x) * k) / view.k, y: my - ((my - view.y) * k) / view.k });
  };
  const zoom = (f: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    const mx = r.width / 2, my = r.height / 2;
    const k = Math.min(2.2, Math.max(0.2, view.k * f));
    setView({ k, x: mx - ((mx - view.x) * k) / view.k, y: my - ((my - view.y) * k) / view.k });
  };
  const relayout = () => {
    const layout = autoLayout(p.nodes, layoutEdges(p.edges));
    setPos(layout);
    p.onPositionsChange?.(layout);
    fitted.current = "";
  };

  const onPointerDownBg = (e: RPE<SVGSVGElement>) => {
    setHintVisible(false);
    if (e.button !== 0) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setDrag({ kind: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y });
  };
  const onPointerDownNode = (e: RPE, id: number) => {
    e.stopPropagation();
    if (e.button !== 0) return;
    setDrag({ kind: "node", id, sx: e.clientX, sy: e.clientY, ox: pos[id].x, oy: pos[id].y });
  };
  const onPointerDownHandle = (e: RPE, id: number) => {
    e.stopPropagation();
    setDrag({ kind: "connect", id, sx: e.clientX, sy: e.clientY, ox: 0, oy: 0 });
    setCursor(toWorld(e.clientX, e.clientY));
  };
  const onPointerMove = (e: RPE<SVGSVGElement>) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (drag.kind === "pan") setView((v) => ({ ...v, x: drag.ox + dx, y: drag.oy + dy }));
    else if (drag.kind === "node" && p.editable) {
      if (Math.abs(dx) + Math.abs(dy) > 3) setDrag({ ...drag, moved: true });
      setPos((ps) => ({ ...ps, [drag.id!]: { x: Math.round(drag.ox + dx / view.k), y: Math.round(drag.oy + dy / view.k) } }));
    } else if (drag.kind === "connect") {
      setCursor(toWorld(e.clientX, e.clientY));
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-node-id]");
      const t = el ? Number(el.getAttribute("data-node-id")) : null;
      setHoverTarget(t && t !== drag.id ? t : null);
    }
  };
  const onPointerUp = (e: RPE<SVGSVGElement>) => {
    if (!drag) return;
    if (drag.kind === "pan" && Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) < 4) {
      p.onSelectNode?.(null);
      p.onSelectEdge?.(null);
    }
    if (drag.kind === "node") {
      if (drag.moved && p.editable) p.onPositionsChange?.({ [drag.id!]: pos[drag.id!] });
      else p.onSelectNode?.(drag.id!);
    }
    if (drag.kind === "connect" && hoverTarget && p.onConnect) p.onConnect(drag.id!, hoverTarget);
    setDrag(null);
    setCursor(null);
    setHoverTarget(null);
  };

  const propagationSet = useMemo(() => new Set((p.propagationEdges || []).map((e) => `${e.to}>${e.from}`)), [p.propagationEdges]);
  const nodeById = useMemo(() => Object.fromEntries(p.nodes.map((n) => [n.id, n])), [p.nodes]);

  const anchor = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const fc = { x: from.x + NODE_W / 2, y: from.y + NODE_H / 2 };
    const tc = { x: to.x + NODE_W / 2, y: to.y + NODE_H / 2 };
    const dy = tc.y - fc.y, dx = tc.x - fc.x;
    if (Math.abs(dy) > NODE_H * 0.8) {
      const s = { x: fc.x, y: dy > 0 ? from.y + NODE_H : from.y };
      const t = { x: tc.x, y: dy > 0 ? to.y : to.y + NODE_H };
      const c = Math.max(30, Math.abs(t.y - s.y) / 2);
      return { d: `M${s.x},${s.y} C${s.x},${s.y + (dy > 0 ? c : -c)} ${t.x},${t.y - (dy > 0 ? c : -c)} ${t.x},${t.y}`, mid: { x: (s.x + t.x) / 2, y: (s.y + t.y) / 2 } };
    }
    const s = { x: dx > 0 ? from.x + NODE_W : from.x, y: fc.y };
    const t = { x: dx > 0 ? to.x : to.x + NODE_W, y: tc.y };
    const c = Math.max(30, Math.abs(t.x - s.x) / 2);
    return { d: `M${s.x},${s.y} C${s.x + (dx > 0 ? c : -c)},${s.y} ${t.x - (dx > 0 ? c : -c)},${t.y} ${t.x},${t.y}`, mid: { x: (s.x + t.x) / 2, y: (s.y + t.y) / 2 } };
  };

  const ready = p.nodes.every((n) => pos[n.id]);
  return (
    <div className="graph-wrap">
      {p.hint && hintVisible && <div className="graph-hint">{p.hint}</div>}
      <svg ref={svgRef} className={`graph ${drag?.kind === "pan" ? "panning" : ""}`} onWheel={onWheel}
        onPointerDown={onPointerDownBg} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}
        role="application" aria-label="Architecture dependency graph">
        <defs>
          {[["arrow", "#4a7c8c"], ["arrow-red", "#ff6b66"], ["arrow-cyan", "#a69bff"]].map(([id, c]) => (
            <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={c} />
            </marker>
          ))}
        </defs>
        {ready && <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {p.edges.map((e) => {
            const s = pos[e.source_component_id], t = pos[e.target_component_id];
            if (!s || !t) return null;
            const { d } = anchor(s, t);
            const prop = propagationSet.has(`${e.source_component_id}>${e.target_component_id}`);
            const dim = p.focusIds && !(p.focusIds.has(e.source_component_id) && p.focusIds.has(e.target_component_id));
            const fb = e.fallback_component_id ? pos[e.fallback_component_id] : null;
            return (
              <g key={e.id}>
                {fb && <path className={`edge fallback ${dim ? "dim" : ""}`} d={anchor(s, fb).d} markerEnd="url(#arrow-cyan)" />}
                <path className={`edge ${e.dependency_type === "OPTIONAL" ? "optional" : ""} ${prop ? "propagation" : ""} ${p.selectedEdgeId === e.id ? "selected" : ""} ${dim && !prop ? "dim" : ""}`}
                  d={d} markerEnd={prop ? "url(#arrow-red)" : p.selectedEdgeId === e.id ? "url(#arrow-cyan)" : "url(#arrow)"} />
                {p.onSelectEdge && <path className="edge-hit" d={d} onPointerDown={(ev) => { ev.stopPropagation(); p.onSelectEdge!(e.id); p.onSelectNode?.(null); }}>
                  <title>{`${nodeById[e.source_component_id]?.name} depends on ${nodeById[e.target_component_id]?.name} (${e.dependency_type.toLowerCase()})`}</title>
                </path>}
              </g>
            );
          })}
          {drag?.kind === "connect" && cursor && pos[drag.id!] && (
            <line x1={pos[drag.id!].x + NODE_W / 2} y1={pos[drag.id!].y + NODE_H} x2={cursor.x} y2={cursor.y} stroke="#a69bff" strokeWidth={1.8} strokeDasharray="5 4" markerEnd="url(#arrow-cyan)" />
          )}
          {p.nodes.map((n) => {
            const q = pos[n.id];
            const color = STATUS_COLOR[n.status] || "#5e7c85";
            const imp = p.impact?.[n.id];
            const dim = p.focusIds && !p.focusIds.has(n.id);
            return (
              <g key={n.id} data-node-id={n.id} className={`node ${p.selectedId === n.id ? "selected" : ""}`} transform={`translate(${q.x},${q.y})`}
                opacity={dim ? 0.35 : 1} onPointerDown={(e) => onPointerDownNode(e, n.id)} style={{ cursor: p.editable ? "move" : "pointer" }}>
                <title>{`${n.name} · ${TYPE_LABEL[n.component_type]} · ${n.status} · health ${Math.round(n.health)}% · ${n.criticality}`}</title>
                <rect className="node-rect" width={NODE_W} height={NODE_H} rx={9}
                  style={hoverTarget === n.id ? { stroke: "#a69bff", strokeWidth: 2 } : imp ? { stroke: IMPACT_COLOR[imp], strokeWidth: 1.8 } : undefined} />
                <rect width={4} height={NODE_H - 16} x={0} y={8} rx={2} fill={color} />
                <g transform="translate(14,12)" color={color}><TypeIcon type={n.component_type} size={15} /></g>
                <text className="node-name" x={36} y={24}>{n.name.length > 21 ? n.name.slice(0, 20) + "…" : n.name}</text>
                <text className="node-sub" x={36} y={42}>{n.status.toLowerCase()} · {Math.round(n.health)}% · {n.criticality.toLowerCase()}</text>
                <rect x={NODE_W - 50} y={NODE_H - 10} width={40} height={3} rx={1.5} fill="#22434f" />
                <rect x={NODE_W - 50} y={NODE_H - 10} width={40 * Math.max(0, Math.min(1, n.health / 100))} height={3} rx={1.5} fill={color} />
                {imp && <g transform={`translate(${NODE_W - 64},-9)`}>
                  <rect width={60} height={17} rx={8.5} fill="#0f2229" stroke={IMPACT_COLOR[imp]} />
                  <text x={30} y={12} textAnchor="middle" fontSize={9.5} fontWeight={700} fill={IMPACT_COLOR[imp]}>{imp}</text>
                </g>}
                {p.badges?.[n.id] && <g transform="translate(-9,-9)">
                  <circle cx={10} cy={10} r={10} fill="#a69bff" stroke="#0f2229" strokeWidth={2} />
                  <text x={10} y={14} textAnchor="middle" fontSize={10.5} fontWeight={700} fill="#0f2229">{p.badges[n.id]}</text>
                </g>}
                {p.editable && p.onConnect && <circle className="node-handle" cx={NODE_W / 2} cy={NODE_H} r={6}
                  onPointerDown={(e) => onPointerDownHandle(e, n.id)}><title>Drag onto another component to add a dependency</title></circle>}
              </g>
            );
          })}
        </g>}
      </svg>
      <div className="graph-toolbar">
        <button className="btn sm icon" title="Zoom in" aria-label="Zoom in" onClick={() => zoom(1.2)}><LuZoomIn /></button>
        <button className="btn sm icon" title="Zoom out" aria-label="Zoom out" onClick={() => zoom(1 / 1.2)}><LuZoomOut /></button>
        <button className="btn sm icon" title="Fit to view" aria-label="Fit to view" onClick={fit}><LuMaximize /></button>
        <button className="btn sm" title="Arrange automatically (layered layout)" onClick={relayout}><LuLayoutDashboard />Auto-arrange</button>
      </div>
      {p.showLegend !== false && (
        <div className="graph-legend">
          {Object.entries(STATUS_COLOR).map(([k, c]) => <span key={k}><span className="legend-dot" style={{ background: c }} />{k.toLowerCase()}</span>)}
          <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#6a98a8" strokeWidth="1.6" /></svg>mandatory</span>
          <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#6a98a8" strokeWidth="1.6" strokeDasharray="4 3" /></svg>optional</span>
          <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#a69bff" strokeWidth="1.4" strokeDasharray="2 3" /></svg>backup</span>
          {p.propagationEdges && <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#ff6b66" strokeWidth="2" strokeDasharray="5 3" /></svg>propagation</span>}
          <span className="faint">arrow = “depends on”</span>
        </div>
      )}
    </div>
  );
}
