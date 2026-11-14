import { useMemo, useState } from "react";
import { LuCrosshair, LuSearch, LuWrench } from "react-icons/lu";
import { api } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { navigate } from "../lib/router";
import GraphCanvas from "../components/GraphCanvas";
import { SimSelector, useProjectSimulation } from "../components/SimSelector";
import { Badge, Callout, Card, Loading, PageHeader, PathView, Progress } from "../components/ui";
import { NoSimulation } from "./Impact";

export default function RootCausePage({ pid }: { pid: number }) {
  const { sims, selected, select, loading } = useProjectSimulation(pid);
  const arch = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const rca = useApi<any>(selected ? `/simulations/${selected.id}/root-cause` : null, [selected?.id]);
  const sim = useApi<any>(selected ? `/simulations/${selected.id}` : null, [selected?.id]);
  const [observed, setObserved] = useState<number[]>([]);
  const [diag, setDiag] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const { error } = useFeedback();

  const r = rca.data;
  const roots = useMemo(() => new Set<number>([...(r?.verified_causes || []).map((v: any) => v.component_id), ...(r?.inferred_candidates || []).map((c: any) => c.component_id)]), [r]);
  const impactMap = useMemo(() => {
    const m: Record<number, string> = {};
    (sim.data?.results || []).forEach((x: any) => { if (x.impact_type !== "UNAFFECTED" && sim.data.revealed_component_ids.includes(x.component_id)) m[x.component_id] = x.impact_type; });
    return m;
  }, [sim.data]);
  const nodes = useMemo(() => (arch.data?.components || []).map((c: any) => {
    const x = (sim.data?.results || []).find((y: any) => y.component_id === c.id && sim.data.revealed_component_ids.includes(c.id));
    return x ? { ...c, status: x.status } : { ...c, status: c.baseline_status, health: c.baseline_health };
  }), [arch.data, sim.data]);

  const diagnose = async () => {
    setBusy(true);
    try { setDiag(await api.post(`/projects/${pid}/diagnose`, { observed_component_ids: observed })); } catch (e) { error(e); } finally { setBusy(false); }
  };

  if (loading || (arch.loading && !arch.data)) return <Loading />;
  const header = <PageHeader title="Root Cause Analysis" description="Separates verified simulation causes from causes inferred purely from observed statuses and the dependency graph."
    actions={<SimSelector sims={sims} selected={selected} onSelect={select} />} />;

  const diagnosis = (
    <Card title="Symptom-based diagnosis" icon={<LuCrosshair />} sub="Select components observed as unavailable; ResQLens ranks potential root causes (no simulation needed).">
      <div className="chips">{(arch.data?.components || []).map((c: any) => (
        <label key={c.id} className="chip check" style={{ background: observed.includes(c.id) ? "var(--accent-soft)" : undefined, borderColor: observed.includes(c.id) ? "rgba(59,130,246,.5)" : undefined }}>
          <input type="checkbox" checked={observed.includes(c.id)} onChange={(e) => setObserved(e.target.checked ? [...observed, c.id] : observed.filter((x) => x !== c.id))} />{c.name}
        </label>))}</div>
      <div className="row mt12"><button className="btn primary sm" disabled={!observed.length || busy} onClick={diagnose}><LuSearch />Diagnose</button>
        {observed.length > 0 && <button className="btn ghost sm" onClick={() => { setObserved([]); setDiag(null); }}>Clear</button>}</div>
      {diag && (
        <div className="mt16 col" style={{ gap: 10 }}>
          <Callout kind="info">{diag.note}</Callout>
          {diag.discrimination_hint && <Callout kind="warn">{diag.discrimination_hint}</Callout>}
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Candidate</th><th style={{ width: 150 }}>Coverage</th><th style={{ width: 150 }}>Consistency</th><th>Explanation</th></tr></thead>
            <tbody>{diag.candidates.map((c: any) => (
              <tr key={c.component_id}>
                <td><div className="row"><span className="strong">{c.name}</span><Badge value="INFERRED" /></div>{c.is_deepest_common_dependency && <div className="xs" style={{ color: "var(--cyan)" }}>deepest common dependency</div>}</td>
                <td><div className="bar-inline"><Progress value={c.coverage} /><span className="num xs">{Math.round(c.coverage * 100)}%</span></div></td>
                <td><div className="bar-inline"><Progress value={c.consistency} color="var(--cyan)" /><span className="num xs">{Math.round(c.consistency * 100)}%</span></div></td>
                <td className="small muted">{c.explanation}</td>
              </tr>))}</tbody></table></div>
        </div>
      )}
    </Card>
  );

  if (!selected) return <>{header}<NoSimulation pid={pid} /><div className="mt16">{diagnosis}</div></>;
  if (rca.loading && !r) return <>{header}<Loading /></>;
  if (rca.error || !r) return <>{header}<Callout kind="error">{rca.error?.message}</Callout></>;

  return (
    <>
      {header}
      <Callout kind="info">{r.method}</Callout>
      <div className="grid g-main mt16">
        <div className="col" style={{ gap: 14 }}>
          <div className="grid g2">
            <Card title="Verified causes" sub="Failure events injected into this simulation">
              <div className="col" style={{ gap: 10 }}>{r.verified_causes.map((v: any) => (
                <div key={v.component_id} className="callout" style={{ borderColor: "rgba(34,211,238,.4)" }}>
                  <div className="col" style={{ gap: 6 }}><div className="row"><span className="strong">{v.component_name}</span><Badge value="VERIFIED" /></div>
                    <span className="small">{v.explanation}</span>{v.description && <span className="faint xs">“{v.description}”</span>}</div>
                </div>))}</div>
            </Card>
            <Card title="Inferred root-cause candidates" sub="From statuses + dependency rules (R1–R3)">
              <div className="col" style={{ gap: 10 }}>{r.inferred_candidates.map((c: any) => (
                <div key={c.component_id} className="callout">
                  <div className="col w100" style={{ gap: 6 }}>
                    <div className="row"><span className="strong">{c.name}</span><Badge value="INFERRED" />{c.matches_verified && <span className="xs" style={{ color: "var(--healthy)" }}>matches simulation</span>}</div>
                    <div className="bar-inline"><span className="xs muted">coverage</span><Progress value={c.coverage} /><span className="num xs">{Math.round(c.coverage * 100)}%</span></div>
                    <span className="small">{c.explanation}</span>
                  </div>
                </div>))}
                {r.inference_consistent_with_simulation === true && <Callout kind="success">Status-only inference agrees with the verified simulation causes.</Callout>}
                {r.inference_consistent_with_simulation === false && <Callout kind="warn">Inference does not isolate every verified cause – e.g. a source whose symptoms are explained by an upstream failure.</Callout>}
              </div>
            </Card>
          </div>
          <Card title="Dependency trace" sub="Root causes are outlined; arrows point from a component to what it depends on" bodyClass="">
            <div style={{ height: 400, display: "flex" }}>
              <GraphCanvas nodes={nodes} edges={arch.data.dependencies} impact={impactMap} focusIds={roots.size ? new Set([...roots, ...Object.keys(impactMap).map(Number)]) : null}
                propagationEdges={(sim.data?.results || []).flatMap((x: any) => sim.data.revealed_component_ids.includes(x.component_id) ? x.causes.map((c: number) => ({ from: c, to: x.component_id })) : [])} />
            </div>
          </Card>
          {diagnosis}
        </div>
        <div className="col" style={{ gap: 14 }}>
          <Card title="Secondary effects" sub="Not root causes – traced upstream (R2)">
            {r.secondary_effects.length === 0 ? <span className="muted small">No secondary effects.</span> : (
              <div className="col" style={{ gap: 12 }}>{r.secondary_effects.map((s: any) => (
                <div key={s.component_id}>
                  <div className="row small"><span className="strong">{s.name}</span><Badge value={s.status} />{s.is_verified_source && <Badge value="VERIFIED" label="also injected" />}</div>
                  <div className="mt8" style={{ marginTop: 4 }}><PathView names={s.trace} /></div>
                  <div className="faint xs" style={{ marginTop: 4 }}>Traced to: {s.traced_to.join(", ") || "–"}</div>
                </div>))}</div>
            )}
          </Card>
          <Card title="Common upstream dependencies" sub="Unhealthy components shared by every secondary effect (R4)">
            {r.common_upstream_dependencies.length === 0 ? <span className="muted small">None – the effects do not share a single upstream cause.</span> :
              <div className="chips">{r.common_upstream_dependencies.map((c: any) => <span key={c.component_id} className="chip">{c.name} · {c.status.toLowerCase()}</span>)}</div>}
          </Card>
          <button className="btn primary" onClick={() => navigate(`/projects/${pid}/recovery?sim=${selected.id}`)}><LuWrench />Plan recovery</button>
        </div>
      </div>
    </>
  );
}
