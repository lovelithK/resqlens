// Shared hook + selector for the "current simulation" used by analysis pages.
import { useEffect, useMemo } from "react";
import { useApi } from "../lib/hooks";
import { useQueryParam } from "../lib/router";
import { ACTIVE_SIM, fmtDate } from "../lib/format";

export type SimRow = {
  id: number; name: string; status: string; failure_type: string; impact_score: number | null; severity_class: string | null;
  created_at: string; failure_sources: string; affected_count: number;
};

export function useProjectSimulation(pid: number, opts: { includeCreated?: boolean } = {}) {
  const sims = useApi<SimRow[]>(`/simulations?project_id=${pid}`, [pid]);
  const [simParam, setSimParam] = useQueryParam("sim");
  const usable = useMemo(() => (sims.data || []).filter((s) => opts.includeCreated || s.status !== "CREATED"), [sims.data, opts.includeCreated]);
  const selected = useMemo(() => {
    if (!usable.length) return null;
    const byParam = simParam ? usable.find((s) => String(s.id) === simParam) : null;
    return byParam || usable.find((s) => ACTIVE_SIM.includes(s.status)) || usable[0];
  }, [usable, simParam]);
  useEffect(() => {
    if (selected && simParam !== String(selected.id)) setSimParam(String(selected.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);
  return { sims: usable, loading: sims.loading, selected, select: (id: number) => setSimParam(String(id)), reload: sims.reload };
}

export function SimSelector({ sims, selected, onSelect }: { sims: SimRow[]; selected: SimRow | null; onSelect: (id: number) => void }) {
  if (!sims.length) return null;
  return (
    <select className="select" style={{ width: 340 }} aria-label="Select simulation" value={selected?.id ?? ""} onChange={(e) => onSelect(+e.target.value)}>
      {sims.map((s) => (
        <option key={s.id} value={s.id}>#{s.id} {s.name} · {s.status.toLowerCase()} · {fmtDate(s.created_at)}</option>
      ))}
    </select>
  );
}
