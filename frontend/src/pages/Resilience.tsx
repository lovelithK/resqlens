import { useState } from "react";
import { LuShieldAlert, LuShieldCheck } from "react-icons/lu";
import { useApi } from "../lib/hooks";
import { fmtDate, minutes, SEVERITY_COLOR, STATUS_COLOR, scoreColor } from "../lib/format";
import { Badge, Callout, Card, Loading, PageHeader, Stat } from "../components/ui";
import { BarChart, Donut, Gauge, LineChart } from "../components/charts";

export default function ResiliencePage({ pid }: { pid: number }) {
  const [model, setModel] = useState("OPERATIONAL");
  const { data: d, loading, error } = useApi<any>(`/projects/${pid}/resilience?model=${model}`, [pid, model]);
  if (loading && !d) return <Loading />;
  if (error || !d) return <Callout kind="error">{error?.message}</Callout>;
  const header = <PageHeader title="Resilience Analytics" description="A transparent score computed from measurable architecture and simulation characteristics."
    actions={<div className="pill-tabs" role="radiogroup" aria-label="Scoring model">
      <button className={model === "OPERATIONAL" ? "on" : ""} onClick={() => setModel("OPERATIONAL")}>Operational</button>
      <button className={model === "DESIGN" ? "on" : ""} onClick={() => setModel("DESIGN")}>Design-time</button></div>} />;
  if (d.empty) return <>{header}<Callout>{d.message}</Callout></>;
  const spofs = d.single_points_of_failure;
  return (
    <>
      {header}
      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <Card title="Resilience score" sub={d.model_name} icon={<LuShieldCheck />}>
            <div className="row" style={{ gap: 26, alignItems: "flex-start", flexWrap: "wrap" }}>
              <Gauge value={d.score} size={170} label="of 100" sub={`Grade ${d.grade}`} />
              <div style={{ flex: 1, minWidth: 300 }}>
                <div className="table-wrap"><table className="table">
                  <thead><tr><th>Factor</th><th style={{ width: 160 }}>Value (0–100)</th><th className="right">Weight</th><th className="right">Points</th></tr></thead>
                  <tbody>{d.breakdown.map((b: any) => (
                    <tr key={b.key} style={{ opacity: b.included ? 1 : 0.5 }}>
                      <td><div className="strong">{b.label}</div><div className="faint xs">{b.detail}</div></td>
                      <td>{b.value !== null ? <div className="bar-inline"><div className="factor-bar" style={{ flex: 1 }}><div style={{ width: `${b.value}%`, background: scoreColor(b.value) }} /></div><span className="num xs">{b.value}</span></div> : <span className="faint xs">excluded</span>}</td>
                      <td className="right num">{b.effective_weight}</td><td className="right num strong">{b.contribution}</td>
                    </tr>))}</tbody></table></div>
                <p className="faint xs mt8">{d.formula}. Grade: A ≥ 85 · B ≥ 70 · C ≥ 55 · D ≥ 40 · F below.</p>
              </div>
            </div>
          </Card>
          <Card title="Single points of failure" icon={<LuShieldAlert />} sub="A component is a SPOF if its single complete failure (what-if) makes a critical functionality unavailable" bodyClass="">
            {spofs.length === 0 ? <div className="card-body"><Callout kind="success">No single points of failure detected.</Callout></div> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Component</th><th>Criticality</th><th className="right">Dependents</th><th>Critical functionality lost</th><th className="right">Blast radius</th><th>Suggested mitigation</th></tr></thead>
                <tbody>{spofs.map((s: any) => (
                  <tr key={s.component_id}><td className="strong">{s.name}<div className="faint xs">backup coverage {s.fallback_coverage}</div></td><td><Badge value={s.criticality} /></td>
                    <td className="right num">{s.dependent_count}</td><td className="small">{s.affected_critical_functionalities.join(", ")}</td>
                    <td className="right num">{Math.round(s.blast_radius * 100)}%</td><td className="small muted" style={{ maxWidth: 360 }}>{s.suggested_mitigation}</td></tr>
                ))}</tbody></table></div>
            )}
          </Card>
          <Card title="Blast radius per component" sub="Share of other components affected by a single complete failure">
            <BarChart data={[...d.spof].sort((a: any, b: any) => b.blast_radius - a.blast_radius).slice(0, 10).map((r: any) => ({ label: r.name, value: Math.round(r.blast_radius * 100), color: r.is_spof ? "#f43f5e" : "#3b82f6" }))} unit="%" height={230} />
          </Card>
        </div>
        <div className="col" style={{ gap: 14 }}>
          <div className="grid g2">
            <Stat label="Critical dependencies" value={d.critical_dependency_count} hint="Mandatory deps on HIGH/CRITICAL components" />
            <Stat label="Single points of failure" value={spofs.length} color={spofs.length ? "var(--blocked)" : "var(--healthy)"} />
            <Stat label="Recovery efficiency" value={d.recovery.efficiency ?? "–"} hint="latest executed plan" />
            <Stat label="Successful recovery ops" value={d.recovery.successful_operations} hint={`${d.recovery.executed_plans} plan(s) executed`} />
            <Stat label="Estimated recovery" value={minutes(d.recovery.estimated_minutes)} />
            <Stat label="Actual simulated recovery" value={minutes(d.recovery.actual_minutes)} />
          </div>
          <Card title="Component health distribution" sub={`Criticality-weighted health ${d.weighted_health}%`}>
            <Donut data={Object.entries(d.health_distribution).map(([k, v]) => ({ label: k.toLowerCase(), value: v as number, color: STATUS_COLOR[k] }))} />
          </Card>
          <Card title="Failure impact distribution" sub="Severity classes of this project's simulations">
            <BarChart data={Object.entries(d.impact_distribution).map(([k, v]) => ({ label: k.toLowerCase(), value: v as number, color: SEVERITY_COLOR[k] }))} height={170} />
          </Card>
          <Card title="Score history" sub="Snapshots recorded after propagation and recovery">
            {d.history.length < 2 ? <span className="muted small">Run simulations to build a history.</span> :
              <LineChart yMax={100} series={[{ name: "score", color: "#22d3ee", points: d.history.map((h: any, i: number) => ({ x: i, y: h.score })) }]} height={160} />}
            {d.history.length > 0 && <div className="faint xs mt8">Latest: {d.history[d.history.length - 1].score} ({d.history[d.history.length - 1].trigger.toLowerCase()}) · {fmtDate(d.history[d.history.length - 1].created_at)}</div>}
          </Card>
          <Card title="Architecture">
            <dl className="kv">
              <dt>Components</dt><dd>{d.architecture.component_count}</dd>
              <dt>Dependencies</dt><dd>{d.architecture.dependency_count} ({d.architecture.mandatory_dependency_count} mandatory)</dd>
              <dt>Configured backups</dt><dd>{d.architecture.fallback_count}</dd>
              <dt>Max depth</dt><dd>{d.architecture.max_depth}</dd>
              <dt>Validation</dt><dd>{d.validation.valid ? "valid" : `${d.validation.error_count} error(s)`}</dd>
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}
