import { useMemo, useState } from "react";
import { LuGauge, LuSearch, LuWrench, LuZap } from "react-icons/lu";
import { useApi } from "../lib/hooks";
import { navigate } from "../lib/router";
import { IMPACT_COLOR, SEVERITY_COLOR } from "../lib/format";
import GraphCanvas from "../components/GraphCanvas";
import { SimSelector, useProjectSimulation } from "../components/SimSelector";
import { Badge, Callout, Card, Empty, Loading, PageHeader, PathView, Stat } from "../components/ui";
import { BarChart, Gauge } from "../components/charts";

export function NoSimulation({ pid }: { pid: number }) {
  return <Card><Empty icon={<LuZap />} title="No simulation to analyse" action={<button className="btn primary" onClick={() => navigate(`/projects/${pid}/simulation`)}><LuZap />Run a simulation</button>}>
    Run a failure simulation first; its results appear here.</Empty></Card>;
}

export default function ImpactPage({ pid }: { pid: number }) {
  const { sims, selected, select, loading } = useProjectSimulation(pid);
  const arch = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const impact = useApi<any>(selected ? `/simulations/${selected.id}/impact` : null, [selected?.id]);
  const [inspect, setInspect] = useState<number | null>(null);
  const [pathFocus, setPathFocus] = useState<number[] | null>(null);
  const d = impact.data;

  const impactMap = useMemo(() => {
    const m: Record<number, string> = {};
    (d?.components || []).forEach((c: any) => { m[c.component_id] = c.impact_type; });
    return m;
  }, [d]);
  const nodes = useMemo(() => (arch.data?.components || []).map((c: any) => {
    const r = d?.components.find((x: any) => x.component_id === c.id);
    return r ? { ...c, status: r.status } : { ...c, status: c.baseline_status, health: c.baseline_health };
  }), [arch.data, d]);

  if (loading || (arch.loading && !arch.data)) return <Loading />;
  const header = <PageHeader title="Impact Analysis" description="Consequences of the simulated failure, scored with a documented weighted model."
    actions={<SimSelector sims={sims} selected={selected} onSelect={select} />} />;
  if (!selected) return <>{header}<NoSimulation pid={pid} /></>;
  if (impact.loading && !d) return <>{header}<Loading /></>;
  if (impact.error || !d) return <>{header}<Callout kind="error">{impact.error?.message}</Callout></>;

  const sel = inspect ? d.components.find((c: any) => c.component_id === inspect) : null;
  return (
    <>
      {header}
      {d.source === "stored" && <Callout kind="info">This simulation has been {d.simulation_status === "RESET" ? "reset" : "recovered"}; showing the impact recorded when propagation finished.</Callout>}
      <div className="grid g-stats mb16 mt12">
        <div className="card stat" style={{ alignItems: "center", flexDirection: "row", gap: 12 }}>
          <Gauge value={d.impact_score} size={96} />
          <div className="col" style={{ gap: 4 }}><span className="muted small">Impact score</span><Badge value={d.severity_class} /></div>
        </div>
        <Stat label="Failure sources" value={d.source_count} color={IMPACT_COLOR.SOURCE} />
        <Stat label="Directly affected" value={d.direct_count} color={IMPACT_COLOR.DIRECT} />
        <Stat label="Indirectly affected" value={d.indirect_count} color={IMPACT_COLOR.INDIRECT} />
        <Stat label="Total affected" value={`${d.total_affected}/${d.component_count}`} hint={`${d.unaffected_count} unaffected`} />
        <Stat label="Functionality unavailable" value={`${d.unavailable_functionality_count}/${d.functionality_count}`} hint={`${d.degraded_functionality_count} degraded`} color={d.unavailable_functionality_count ? "var(--failed)" : undefined} />
        <Stat label="Dependency depth" value={d.dependency_depth} hint={`${d.mandatory_propagation_edges} mandatory · ${d.optional_propagation_edges} optional edges`} />
      </div>

      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <Card title="Propagation map" sub="Red dashed edges show how the failure travelled. Click a component to inspect it." bodyClass="">
            <div style={{ height: 430, display: "flex" }}>
              <GraphCanvas nodes={nodes} edges={arch.data.dependencies} impact={impactMap}
                propagationEdges={d.propagation_edges || []} selectedId={inspect} onSelectNode={setInspect}
                focusIds={pathFocus ? new Set(pathFocus) : null} />
            </div>
          </Card>
          <Card title="Affected components" sub="Ordered by propagation depth" bodyClass="">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Component</th><th>Impact</th><th>Status</th><th>Criticality</th><th className="right">Depth</th><th>Reason</th></tr></thead>
              <tbody>{d.components.map((c: any) => (
                <tr key={c.component_id} className={`clickable ${inspect === c.component_id ? "selected" : ""}`} onClick={() => setInspect(c.component_id)}>
                  <td className="strong">{c.name}</td><td><Badge value={c.impact_type} /></td><td><Badge value={c.status} /></td>
                  <td><Badge value={c.criticality} /></td><td className="right num">{c.depth}</td><td className="small muted">{c.reason}</td>
                </tr>))}</tbody></table></div>
          </Card>
          <Card title="Propagation paths" sub="Every source → leaf path through the cascade. Click to focus it on the map.">
            {d.propagation_paths.length === 0 ? <span className="muted small">The failure did not propagate beyond its source(s).</span> : (
              <div className="col" style={{ gap: 8 }}>
                {pathFocus && <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setPathFocus(null)}>Clear focus</button>}
                {d.propagation_paths.map((p: any, i: number) => (
                  <div key={i} style={{ cursor: "pointer", opacity: pathFocus && pathFocus.join() !== p.ids.join() ? 0.5 : 1 }} onClick={() => setPathFocus(p.ids)}><PathView names={p.names} /></div>
                ))}
              </div>
            )}
          </Card>
        </div>
        <div className="col" style={{ gap: 14 }}>
          {sel && (
            <Card title={sel.name} sub="Inspected component" actions={<button className="btn ghost sm" onClick={() => setInspect(null)}>Close</button>}>
              <div className="row mb12"><Badge value={sel.impact_type} /><Badge value={sel.status} /><Badge value={sel.criticality} /></div>
              <dl className="kv"><dt>Reason</dt><dd>{sel.reason}</dd><dt>Depth</dt><dd>{sel.depth}</dd><dt>Dependents</dt><dd>{sel.dependents}</dd>
                <dt>Path</dt><dd><PathView names={sel.path} /></dd><dt>Functionality</dt><dd>{sel.functionalities.join(", ") || "–"}</dd></dl>
            </Card>
          )}
          <Card title="How the score is calculated" icon={<LuGauge />}>
            <BarChart horizontal data={d.factors.filter((f: any) => f.included).map((f: any) => ({ label: `${f.label} (w ${f.effective_weight})`, value: f.contribution, color: SEVERITY_COLOR[d.severity_class] }))} max={Math.max(35, ...d.factors.map((f: any) => f.contribution))} />
            <div className="table-wrap mt12"><table className="table">
              <thead><tr><th>Factor</th><th className="right">Value</th><th className="right">Weight</th><th className="right">Points</th></tr></thead>
              <tbody>{d.factors.map((f: any) => (
                <tr key={f.key} title={f.definition}><td>{f.label}<div className="faint xs">{f.definition}</div></td><td className="right num">{f.value ?? "n/a"}</td><td className="right num">{f.effective_weight}</td><td className="right num strong">{f.contribution}</td></tr>
              ))}</tbody></table></div>
            <p className="small muted mt12">{d.explanation}</p>
            <p className="xs faint mt8">Classes: &lt;25 low · &lt;50 moderate · &lt;75 high · ≥75 critical.</p>
          </Card>
          <Card title="Functionality availability">
            <div className="col" style={{ gap: 8 }}>{d.functionalities.map((f: any) => (
              <div key={f.id} className="list-item" style={{ padding: "6px 0" }}>
                <div className="row small"><span className="strong">{f.name}</span>{f.is_critical && <span className="faint xs">critical</span>}<div className="spacer" /><Badge value={f.status} /></div>
                {f.blocking_components.length > 0 && <div className="faint xs">Blocked by: {f.blocking_components.join(", ")}</div>}
              </div>
            ))}</div>
          </Card>
          <Card title="Critical components affected">
            {d.critical_components_affected.length === 0 ? <span className="muted small">No high or critical components affected.</span> :
              <div className="chips">{d.critical_components_affected.map((c: any) => <span key={c.component_id} className="chip">{c.name} · {c.criticality.toLowerCase()}</span>)}</div>}
          </Card>
          <div className="row">
            <button className="btn" onClick={() => navigate(`/projects/${pid}/root-cause?sim=${selected.id}`)}><LuSearch />Root cause</button>
            <button className="btn primary" onClick={() => navigate(`/projects/${pid}/recovery?sim=${selected.id}`)}><LuWrench />Plan recovery</button>
          </div>
        </div>
      </div>
    </>
  );
}
