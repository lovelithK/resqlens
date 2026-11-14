// Layered auto-layout for the dependency graph (Sugiyama-style, simplified):
// 1. longest-path layering (components without dependencies at the bottom),
// 2. barycenter ordering within layers (a few sweeps) to reduce edge crossings,
// 3. even spacing. Deterministic for a given graph.
export type LNode = { id: number; name: string };
export type LEdge = { source: number; target: number };
// (backup/fallback links are passed in as ordinary edges so backups sit next to their primaries)

export const NODE_W = 196;
export const NODE_H = 60;
const GAP_X = 40;
const GAP_Y = 64;

export function autoLayout(nodes: LNode[], edges: LEdge[]): Record<number, { x: number; y: number }> {
  const deps = new Map<number, number[]>();
  const users = new Map<number, number[]>();
  nodes.forEach((n) => { deps.set(n.id, []); users.set(n.id, []); });
  edges.forEach((e) => {
    if (deps.has(e.source) && deps.has(e.target)) {
      deps.get(e.source)!.push(e.target);
      users.get(e.target)!.push(e.source);
    }
  });
  // longest path to a sink (guarded against cycles)
  const layer = new Map<number, number>();
  const visiting = new Set<number>();
  const depth = (id: number): number => {
    if (layer.has(id)) return layer.get(id)!;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const d = deps.get(id)!;
    const v = d.length ? 1 + Math.max(...d.map(depth)) : 0;
    visiting.delete(id);
    layer.set(id, v);
    return v;
  };
  nodes.forEach((n) => depth(n.id));
  const maxL = Math.max(0, ...Array.from(layer.values()));
  // row index from the top; components without dependencies are placed directly below
  // their lowest dependent instead of all sinking to the bottom row (keeps rows narrow)
  const top = new Map<number, number>();
  nodes.forEach((n) => top.set(n.id, maxL - layer.get(n.id)!));
  nodes.forEach((n) => {
    if (deps.get(n.id)!.length === 0 && users.get(n.id)!.length > 0) {
      top.set(n.id, Math.max(...users.get(n.id)!.map((u) => maxL - layer.get(u)!)) + 1);
    }
  });
  const rows: number[][] = Array.from({ length: maxL + 1 }, () => []);
  [...nodes].sort((a, b) => a.name.localeCompare(b.name)).forEach((n) => rows[Math.min(maxL, top.get(n.id)!)].push(n.id));

  const pos = new Map<number, number>();
  const assign = () => rows.forEach((r) => r.forEach((id, i) => pos.set(id, i - (r.length - 1) / 2)));
  assign();
  for (let sweep = 0; sweep < 6; sweep++) {
    const order = sweep % 2 === 0 ? rows.map((_, i) => i) : rows.map((_, i) => rows.length - 1 - i);
    order.forEach((ri) => {
      const r = rows[ri];
      const bary = (id: number) => {
        const nb = [...deps.get(id)!, ...users.get(id)!].filter((x) => pos.has(x));
        return nb.length ? nb.reduce((s, x) => s + pos.get(x)!, 0) / nb.length : pos.get(id)!;
      };
      const scored = r.map((id) => ({ id, b: bary(id) }));
      scored.sort((a, b) => a.b - b.b || a.id - b.id);
      rows[ri] = scored.map((s) => s.id);
      rows[ri].forEach((id, i) => pos.set(id, i - (rows[ri].length - 1) / 2));
    });
  }
  const out: Record<number, { x: number; y: number }> = {};
  rows.filter((r) => r.length).forEach((r, ri) => r.forEach((id, i) => {
    out[id] = { x: Math.round((i - (r.length - 1) / 2) * (NODE_W + GAP_X)), y: ri * (NODE_H + GAP_Y) };
  }));
  return out;
}
