import { useState } from "react";
import { LuGitCompare, LuPlus, LuTrash2 } from "react-icons/lu";
import { api } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { minutes, SEVERITY_COLOR } from "../lib/format";
import { Badge, Callout, Card, Field, Loading, PageHeader } from "../components/ui";
import { BarChart } from "../components/charts";

export default function WhatIfPage({ pid }: { pid: number }) {
  const scenarios = useApi<any[]>(`/projects/${pid}/scenarios`, [pid]);
  const arch = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const catalog = useApi<any>("/catalog");
  const { error, toast, confirm } = useFeedback();
  const [chosen, setChosen] = useState<number[]>([]);
  const [custom, setCustom] = useState({ component_id: "", failure_type: "COMPLETE_SERVICE_FAILURE", severity: 7 });
  const [extra, setExtra] = useState<any[]>([]);
  const [result, setResult] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);

  if (scenarios.loading || arch.loading || catalog.loading) return <Loading />;
  const comps: any[] = arch.data?.components || [];
  const name = (id: number) => comps.find((c) => c.id === id)?.name;
  const compare = async () => {
    const payload = [
      ...(scenarios.data || []).filter((s) => chosen.includes(s.id)).map((s) => ({ name: s.name, duration_minutes: s.duration_minutes, failures: s.failures.map((f: any) => ({ component_id: f.component_id, failure_type: f.failure_type, severity: f.severity })) })),
      ...extra,
    ];
    if (payload.length < 1) { toast("warning", "Choose at least one scenario"); return; }
    setBusy(true);
    try { setResult(await api.post(`/projects/${pid}/what-if`, { scenarios: payload })); } catch (e) { error(e); } finally { setBusy(false); }
  };
  const addCustom = () => {
    if (!custom.component_id) return;
    const ft = catalog.data.failure_types.find((t: any) => t.type === custom.failure_type);
    const comp = comps.find((c) => c.id === +custom.component_id);
    if (ft.applicable_types && !ft.applicable_types.includes(comp.component_type)) { toast("warning", `${ft.label} only applies to ${ft.applicable_types.join(", ").toLowerCase()}`); return; }
    setExtra([...extra, { name: `${ft.label} – ${comp.name}`, failures: [{ component_id: +custom.component_id, failure_type: custom.failure_type, severity: custom.severity }] }]);
  };
  const deleteScenario = async (s: any) => {
    if (!await confirm({ title: "Delete scenario?", danger: true, message: `'${s.name}' will be removed from the saved scenarios.` })) return;
    try { await api.del(`/scenarios/${s.id}`); setChosen(chosen.filter((x) => x !== s.id)); scenarios.reload(); } catch (e) { error(e); }
  };

  return (
    <>
      <PageHeader title="What-If Scenario Comparison" description="Dry-run hypothetical failures against the current architecture without changing any state, then compare their consequences." />
      <div className="grid g3">
        <Card title="Saved scenarios" sub="Predefined and user-saved">
          <div className="col" style={{ gap: 8 }}>
            {(scenarios.data || []).map((s) => (
              <div key={s.id} className="row small">
                <label className="check" style={{ flex: 1 }}><input type="checkbox" checked={chosen.includes(s.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, s.id] : chosen.filter((x) => x !== s.id))} />
                  <span><span className="strong">{s.name}</span><div className="faint xs">{s.failures.map((f: any) => `${name(f.component_id)} (${f.failure_type.toLowerCase().replace(/_/g, " ")}, ${f.severity})`).join(" + ")}</div></span></label>
                <button className="btn ghost sm icon" aria-label="Delete scenario" onClick={() => deleteScenario(s)}><LuTrash2 /></button>
              </div>
            ))}
            {!scenarios.data?.length && <span className="muted small">No saved scenarios. Save one from the Failure Simulation page.</span>}
          </div>
        </Card>
        <Card title="Ad-hoc scenario" sub="Single failure, not saved">
          <div className="col" style={{ gap: 10 }}>
            <select className="select sm" aria-label="Component" value={custom.component_id} onChange={(e) => setCustom({ ...custom, component_id: e.target.value })}><option value="">Component…</option>{comps.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <select className="select sm" aria-label="Failure type" value={custom.failure_type} onChange={(e) => setCustom({ ...custom, failure_type: e.target.value })}>{(catalog.data?.failure_types || []).map((t: any) => <option key={t.type} value={t.type}>{t.label}</option>)}</select>
            <Field label={`Severity ${custom.severity}/10`}><input type="range" min={1} max={10} value={custom.severity} onChange={(e) => setCustom({ ...custom, severity: +e.target.value })} /></Field>
            <button className="btn sm" disabled={!custom.component_id} onClick={addCustom}><LuPlus />Add to comparison</button>
            {extra.map((x, i) => <div key={i} className="row small"><span className="chip">{x.name}</span><div className="spacer" /><button className="btn ghost sm icon" aria-label="Remove" onClick={() => setExtra(extra.filter((_, j) => j !== i))}><LuTrash2 /></button></div>)}
          </div>
        </Card>
        <Card title="Run comparison">
          <p className="muted small">Each scenario is propagated with the deterministic engine; recovery time and cost come from a Dependency-First plan built from configured recovery values.</p>
          <button className="btn primary mt12" disabled={busy || chosen.length + extra.length === 0} onClick={compare}><LuGitCompare />Compare {chosen.length + extra.length} scenario(s)</button>
        </Card>
      </div>
      {result && (
        <>
          <Card className="mt16" title="Comparison" bodyClass="">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Scenario</th><th className="right">Affected</th><th className="right">Impact</th><th>Severity</th><th className="right">Critical functionality available</th><th className="right">Recovery time</th><th className="right">Recovery cost</th><th>Unavailable functionality</th></tr></thead>
              <tbody>{result.map((r, i) => (
                <tr key={i}><td className="strong">{r.name}<div className="faint xs">{r.failures.map((f: any) => `${f.component} · ${f.label}`).join(" + ")}</div></td>
                  <td className="right num">{r.affected_components} <span className="faint xs">({r.direct}d/{r.indirect}i)</span></td>
                  <td className="right num strong">{r.impact_score}</td><td><Badge value={r.severity_class} /></td>
                  <td className="right num">{r.critical_functionality_available}/{r.critical_functionality_total}</td>
                  <td className="right num">{minutes(r.recovery_minutes)}</td><td className="right num">{r.recovery_cost}</td>
                  <td className="small muted">{r.unavailable_functionalities.join(", ") || "–"}</td></tr>
              ))}</tbody></table></div>
          </Card>
          <div className="grid g2 mt16">
            <Card title="Impact score"><BarChart data={result.map((r) => ({ label: r.name.replace(/^Scenario \d+: /, ""), value: r.impact_score, color: SEVERITY_COLOR[r.severity_class] }))} max={100} /></Card>
            <Card title="Estimated recovery time (min)"><BarChart data={result.map((r) => ({ label: r.name.replace(/^Scenario \d+: /, ""), value: r.recovery_minutes, color: "#22d3ee" }))} /></Card>
          </div>
          <Callout kind="info">What-if results are not stored and do not change component states.</Callout>
        </>
      )}
    </>
  );
}
