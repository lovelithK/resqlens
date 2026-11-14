import { useEffect, useState } from "react";
import { LuFileDown, LuFileSpreadsheet, LuFileText } from "react-icons/lu";
import { download } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { useQueryParam } from "../lib/router";
import { fmtDate, FAILURE_LABEL, minutes } from "../lib/format";
import { Badge, Callout, Card, Empty, Loading, PageHeader, PathView } from "../components/ui";
import { eventLevel } from "./Dashboard";

function Section({ n, title, children }: { n: number; title: string; children: any }) {
  return <Card className="mb16" title={<><span className="faint">{n}.</span> {title}</>}>{children}</Card>;
}

export default function ReportsPage() {
  const sims = useApi<any[]>("/simulations");
  const [simParam, setSimParam] = useQueryParam("sim");
  const usable = (sims.data || []).filter((s) => s.status !== "CREATED");
  const id = simParam || (usable[0] ? String(usable[0].id) : null);
  useEffect(() => { if (!simParam && id) setSimParam(id); }, [id]);
  const report = useApi<any>(id ? `/simulations/${id}/report` : null, [id]);
  const { error } = useFeedback();
  const [busy, setBusy] = useState(false);
  const r = report.data;

  const pdf = async () => {
    setBusy(true);
    try { await download(`/simulations/${id}/report.pdf`, `resqlens-simulation-${id}.pdf`); } catch (e) { error(e); } finally { setBusy(false); }
  };
  const header = <PageHeader title="Reports" description="Professional simulation report: architecture, scenario, root cause, impact, recovery and resilience."
    actions={<>
      <select className="select" style={{ width: 360 }} aria-label="Simulation" value={id || ""} onChange={(e) => setSimParam(e.target.value)}>
        {usable.map((s) => <option key={s.id} value={s.id}>#{s.id} {s.name} · {s.project_name}</option>)}
      </select>
      <button className="btn" disabled={!id} onClick={() => download(`/simulations/${id}/export`, `resqlens-simulation-${id}.csv`).catch(error)}><LuFileSpreadsheet />CSV</button>
      <button className="btn primary" disabled={!id || busy} onClick={pdf}>{busy ? <span className="spinner" /> : <LuFileDown />}Download PDF</button>
    </>} />;
  if (sims.loading && !sims.data) return <Loading />;
  if (!usable.length) return <>{header}<Card><Empty icon={<LuFileText />} title="No reports yet">Reports become available once a simulation has been started.</Empty></Card></>;
  if (report.loading && !r) return <>{header}<Loading /></>;
  if (report.error || !r) return <>{header}<Callout kind="error">{report.error?.message}</Callout></>;
  const imp = r.impact;
  const plan = r.recovery_plan;
  const sum = plan?.summary;
  return (
    <>
      {header}
      <Callout>All values come from ResQLens' deterministic, rule-based simulation of the modelled architecture. They are not measurements of a production incident.</Callout>
      <div className="row mt16 mb16 wrap"><h2>{r.simulation.name}</h2><Badge value={r.simulation.status} /><span className="faint small">{r.project.name} · generated {fmtDate(r.generated_at)}</span></div>
      <Section n={1} title="System architecture summary">
        <p className="small">{r.architecture.component_count} components, {r.architecture.dependency_count} dependencies ({r.architecture.mandatory_dependency_count} mandatory, {r.architecture.optional_dependency_count} optional, {r.architecture.fallback_count} with configured backup), {r.architecture.functionality_count} functionalities, max depth {r.architecture.max_depth}. Policy: {r.project.propagation_policy}.</p>
      </Section>
      <Section n={2} title="Failure scenario">
        <p className="small muted mb12">{FAILURE_LABEL[r.simulation.failure_type]} · {r.simulation.duration_minutes} min simulated window · started {fmtDate(r.simulation.started_at)}</p>
        {r.failures.map((f: any) => <div key={f.id} className="row small mb12"><Badge value="SOURCE" /><span className="strong">{f.component_name}</span><span>{f.failure_label} · severity {f.severity}/10 → {f.resulting_status}</span><span className="faint">{f.description}</span></div>)}
      </Section>
      <Section n={3} title="Root cause">
        {(r.root_cause?.verified_causes || []).map((v: any) => <p key={v.component_id} className="small mb12"><Badge value="VERIFIED" /> {v.explanation}</p>)}
        {(r.root_cause?.inferred_candidates || []).map((c: any) => <p key={c.component_id} className="small mb12"><Badge value="INFERRED" /> {c.explanation}</p>)}
      </Section>
      <Section n={4} title="Affected components">
        <div className="table-wrap"><table className="table"><thead><tr><th>Step</th><th>Component</th><th>Status</th><th>Impact</th><th>Reason</th></tr></thead>
          <tbody>{r.propagation_steps.map((s: any) => <tr key={s.component_id}><td className="num">{s.tick}</td><td className="strong">{s.name}</td><td><Badge value={s.status} /></td><td><Badge value={s.impact_type} /></td><td className="small muted">{s.reason}</td></tr>)}</tbody></table></div>
      </Section>
      <Section n={5} title="Impact analysis">
        {imp ? <>
          <div className="row mb12"><span className="strong" style={{ fontSize: 20 }}>{imp.impact_score}</span><Badge value={imp.severity_class} /><span className="muted small">{imp.total_affected} affected · {imp.unavailable_functionality_count}/{imp.functionality_count} functionalities unavailable · depth {imp.dependency_depth}</span></div>
          <p className="small muted">{imp.explanation}</p>
          <div className="col mt12" style={{ gap: 6 }}>{imp.propagation_paths.slice(0, 8).map((p: any, i: number) => <PathView key={i} names={p.names} />)}</div>
        </> : <span className="muted small">Not available.</span>}
      </Section>
      <Section n={6} title="Recovery recommendation">
        {plan ? <>
          <p className="small"><b>{plan.strategy.name}</b>{plan.is_manual && " (manually modified)"} – {plan.strategy.description}</p>
          <ol className="small mt12" style={{ paddingLeft: 18, margin: "12px 0 0" }}>{[...plan.actions].sort((a: any, b: any) => a.order_index - b.order_index).map((a: any) => <li key={a.id} style={{ marginBottom: 6 }}><b>{a.action_label}</b> on {a.component_name} ({minutes(a.estimated_minutes)}) – <span className="muted">{a.explanation.why}</span></li>)}</ol>
        </> : <span className="muted small">No recovery plan generated.</span>}
      </Section>
      <Section n={7} title="Recovery execution results">
        {sum && sum.actions_total !== undefined ? <p className="small">Plan {plan.status.toLowerCase().replace(/_/g, " ")}: {sum.actions_completed}/{sum.actions_total} actions completed, {sum.actions_failed} failed, {sum.retried_actions} retried. Estimated {minutes(sum.estimated_minutes)}, actual simulated {minutes(sum.actual_minutes)}. Health {sum.health_before}% → {sum.health_after}%.</p>
          : <span className="muted small">Recovery has not been executed.</span>}
      </Section>
      <Section n={8} title="Final system health">
        <p className="small">Criticality-weighted health {r.final_health.weighted_health}% · {Object.entries(r.final_health.distribution || {}).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(" · ")}</p>
      </Section>
      <Section n={9} title="Resilience assessment">
        <p className="small mb12">Score <b>{r.resilience.score}</b> (grade {r.resilience.grade}) · {r.resilience.single_points_of_failure?.length || 0} single point(s) of failure.</p>
        <div className="chips">{(r.resilience.breakdown || []).map((b: any) => <span key={b.key} className="chip">{b.label}: {b.value ?? "n/a"}</span>)}</div>
      </Section>
      <Card title="Event timeline">
        <div className="timeline">{r.timeline.map((e: any) => (
          <div key={e.id} className={`tl-item ${eventLevel(e.event_type)}`}><span className="tl-type">{e.event_type.replace(/_/g, " ")}</span><div className="tl-msg">{e.message}</div><div className="tl-time">{fmtDate(e.created_at)}</div></div>
        ))}</div>
      </Card>
    </>
  );
}
