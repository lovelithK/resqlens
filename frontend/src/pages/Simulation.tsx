import { useEffect, useMemo, useState } from "react";
import {
  LuFastForward, LuGauge, LuPause, LuPlay, LuPlus, LuRotateCcw, LuSave, LuSearch, LuSquare, LuStepForward, LuTrash2, LuWrench, LuZap,
} from "react-icons/lu";
import { api } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi, useInterval } from "../lib/hooks";
import { navigate } from "../lib/router";
import { ACTIVE_SIM, FAILURE_LABEL, fmtDate } from "../lib/format";
import GraphCanvas from "../components/GraphCanvas";
import { useProjectSimulation, SimSelector } from "../components/SimSelector";
import { Badge, Callout, Field, Loading, Progress, Tabs } from "../components/ui";
import { ActivityFeed } from "./Dashboard";

type FailureRow = { component_id: number | ""; failure_type: string; severity: number; description: string };
const blankFailure = (): FailureRow => ({ component_id: "", failure_type: "COMPLETE_SERVICE_FAILURE", severity: 7, description: "" });

export default function SimulationPage({ pid }: { pid: number }) {
  const arch = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const catalog = useApi<any>("/catalog");
  const scenarios = useApi<any[]>(`/projects/${pid}/scenarios`, [pid]);
  const { sims, selected, select, reload: reloadSims } = useProjectSimulation(pid, { includeCreated: true });
  const { toast, error, confirm, notify } = useFeedback();
  const [sim, setSim] = useState<any>(null);
  const [mode, setMode] = useState<"configure" | "view">("configure");
  const [tab, setTab] = useState<"sequence" | "timeline">("sequence");
  const [failures, setFailures] = useState<FailureRow[]>([blankFailure()]);
  const [meta, setMeta] = useState({ name: "", description: "", duration_minutes: 30 });
  const [instant, setInstant] = useState(false);
  const [autoplay, setAutoplay] = useState(true);
  const [speed, setSpeed] = useState(1100);
  const [busy, setBusy] = useState(false);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [selectedNode, setSelectedNode] = useState<number | null>(null);

  const loadSim = async (id: number) => {
    try {
      const s = await api.get(`/simulations/${id}`);
      setSim(s);
      setMode("view");
      api.get(`/simulations/${id}/timeline`).then(setTimeline).catch(() => undefined);
    } catch (e) { error(e); }
  };
  useEffect(() => {
    if (selected) loadSim(selected.id);
    else { setSim(null); setMode("configure"); }
  }, [selected?.id]);

  const active = sim && ACTIVE_SIM.includes(sim.status);
  const applyResult = (s: any) => {
    setSim(s);
    notify(s.notifications);
    arch.reload();
    api.get(`/simulations/${s.id}/timeline`).then(setTimeline).catch(() => undefined);
  };
  const act = async (path: string, body: any = {}) => {
    if (!sim) return;
    setBusy(true);
    try { applyResult(await api.post(`/simulations/${sim.id}/${path}`, body)); reloadSims(); } catch (e) { error(e); } finally { setBusy(false); }
  };

  useInterval(async () => {
    if (!sim || busy) return;
    try { applyResult(await api.post(`/simulations/${sim.id}/tick`)); } catch (e) { error(e); setAutoplay(false); }
  }, speed, !!sim && sim.status === "RUNNING" && autoplay);

  const failureTypes: any[] = catalog.data?.failure_types || [];
  const comps: any[] = arch.data?.components || [];
  const compById = useMemo(() => Object.fromEntries(comps.map((c) => [c.id, c])), [comps]);

  const loadScenario = (id: string) => {
    const sc = scenarios.data?.find((s) => String(s.id) === id);
    if (!sc) return;
    setFailures(sc.failures.map((f: any) => ({ component_id: f.component_id, failure_type: f.failure_type, severity: f.severity, description: f.description || "" })));
    setMeta({ name: sc.name, description: sc.description, duration_minutes: sc.duration_minutes });
  };
  const valid = failures.length > 0 && failures.every((f) => f.component_id !== "");
  const createAndStart = async () => {
    if (!valid) { toast("warning", "Select a target component for every failure"); return; }
    setBusy(true);
    try {
      const created = await api.post("/simulations", { project_id: pid, ...meta, name: meta.name || undefined, failures });
      const started = await api.post(`/simulations/${created.id}/start`, { instant });
      applyResult(started);
      setMode("view");
      setAutoplay(true);
      reloadSims();
      select(started.id);
    } catch (e) { error(e); } finally { setBusy(false); }
  };
  const saveScenario = async () => {
    if (!valid) { toast("warning", "Complete the failure configuration first"); return; }
    const name = meta.name || `Scenario ${new Date().toLocaleString()}`;
    try { await api.post(`/projects/${pid}/scenarios`, { name, description: meta.description, duration_minutes: meta.duration_minutes, failures }); toast("success", `Scenario '${name}' saved`); scenarios.reload(); } catch (e) { error(e); }
  };
  const reset = async () => {
    if (!await confirm({ title: "Reset simulation?", message: "All components return to their original baseline state. The simulation stays in history with its results.", confirmLabel: "Reset architecture" })) return;
    await act("reset");
    toast("success", "Architecture reset to its original state");
  };

  if ((arch.loading && !arch.data) || catalog.loading) return <Loading />;
  if (!comps.length) return <div className="content"><Callout kind="warn">This project has no components yet. <a href={`/projects/${pid}/architecture`} onClick={(e) => { e.preventDefault(); navigate(`/projects/${pid}/architecture`); }}>Open the Architecture Builder</a> first.</Callout></div>;

  // graph state -------------------------------------------------------------
  const results: any[] = sim?.results || [];
  const revealed = new Set<number>(sim?.revealed_component_ids || []);
  const historical = sim && sim.status === "RESET";
  const nodes = comps.map((c) => {
    if (historical) {
      const r = results.find((x) => x.component_id === c.id);
      if (r && revealed.has(c.id)) return { ...c, status: r.status, health: r.health };
      return { ...c, status: c.baseline_status, health: c.baseline_health };
    }
    return c;
  });
  const impact: Record<number, string> = {};
  const propEdges: { from: number; to: number }[] = [];
  if (sim && mode === "view") results.forEach((r) => {
    if (revealed.has(r.component_id) && r.impact_type !== "UNAFFECTED") {
      impact[r.component_id] = r.impact_type;
      r.causes.forEach((c: number) => revealed.has(c) && propEdges.push({ from: c, to: r.component_id }));
    }
  });
  const steps: any[] = sim?.propagation_steps || [];
  const ticks = Array.from(new Set(steps.map((s) => s.tick))).sort((a, b) => a - b);
  const multi = failures.length > 1;
  const nodeInfo = selectedNode ? results.find((r) => r.component_id === selectedNode) : null;

  return (
    <div className="split">
      <div className="center">
        <div className="toolbar">
          <SimSelector sims={sims} selected={selected} onSelect={(id) => select(id)} />
          {sim && <Badge value={sim.status} dot />}
          <div className="spacer" />
          {sim?.status === "RUNNING" && <>
            <label className="check xs"><input type="checkbox" checked={autoplay} onChange={(e) => setAutoplay(e.target.checked)} />Auto-advance</label>
            <select className="select sm" style={{ width: 92 }} aria-label="Speed" value={speed} onChange={(e) => setSpeed(+e.target.value)}>
              <option value={1800}>Slow</option><option value={1100}>Normal</option><option value={500}>Fast</option></select>
            <button className="btn sm" disabled={busy} onClick={() => act("tick")}><LuStepForward />Step</button>
            <button className="btn sm" disabled={busy} onClick={() => act("pause")}><LuPause />Pause</button>
          </>}
          {sim?.status === "PAUSED" && <>
            <button className="btn sm" disabled={busy} onClick={() => act("resume")}><LuPlay />Resume</button>
          </>}
          {sim && ["RUNNING", "PAUSED"].includes(sim.status) && <button className="btn sm" disabled={busy} onClick={() => act("stop")}><LuSquare />Stop</button>}
          {sim && sim.status === "CREATED" && <button className="btn sm primary" disabled={busy} onClick={() => act("start", { instant })}><LuPlay />Start</button>}
          {sim && sim.status !== "RESET" && sim.status !== "CREATED" && <button className="btn sm" disabled={busy} onClick={reset}><LuRotateCcw />Reset</button>}
          <button className="btn sm primary" disabled={!!active} title={active ? "Reset or recover the active simulation first" : undefined}
            onClick={() => { setMode("configure"); setSelectedNode(null); }}><LuPlus />New simulation</button>
        </div>
        {sim && mode === "view" && (
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", background: "var(--bg-2)" }}>
            <div className="row small"><span className="muted">Propagation step</span><span className="num strong">{Math.max(0, sim.current_tick)} / {sim.max_tick}</span>
              <span className="faint">· policy {sim.propagation_policy.toLowerCase().replace("_", "-")} · {FAILURE_LABEL[sim.failure_type]}</span>
              {sim.impact_score !== null && <><div className="spacer" /><span className="muted">Impact</span><span className="num strong">{sim.impact_score}</span><Badge value={sim.severity_class} /></>}
            </div>
            <div className="mt8"><Progress value={sim.progress} color={sim.status === "RUNNING" ? "var(--failed)" : undefined} /></div>
          </div>
        )}
        {historical && <div className="banner blue" style={{ margin: "10px 14px 0" }}>Showing the recorded result of a simulation that has been reset. The live architecture is back at its baseline.</div>}
        <GraphCanvas nodes={nodes} edges={arch.data.dependencies} impact={impact} propagationEdges={propEdges}
          selectedId={selectedNode} onSelectNode={setSelectedNode} />
      </div>

      <aside className="side" aria-label="Simulation panel">
        {mode === "configure" ? (
          <div className="side-section col" style={{ gap: 14 }}>
            <div><h2>Configure failure simulation</h2><p className="muted small mt8">Deterministic, rule-based simulation of your modelled architecture – nothing runs on real infrastructure.</p></div>
            {active && <Callout kind="warn">Simulation “{sim.name}” is still active. Reset it (or finish recovery) before starting another one.</Callout>}
            <Field label="Load a predefined scenario">
              <select className="select" defaultValue="" onChange={(e) => loadScenario(e.target.value)}>
                <option value="" disabled>Choose scenario…</option>
                {(scenarios.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <div className="divider" style={{ margin: 0 }} />
            <div className="row"><span className="section-title" style={{ margin: 0 }}>Failures</span>{multi && <Badge value="CRITICAL" label="Multiple simultaneous failures" />}</div>
            {failures.map((f, i) => {
              const comp = f.component_id ? compById[f.component_id] : null;
              const allowed = failureTypes.filter((t) => !t.applicable_types || !comp || t.applicable_types.includes(comp.component_type));
              const ft = failureTypes.find((t) => t.type === f.failure_type);
              const upd = (k: string, v: any) => setFailures(failures.map((x, j) => j === i ? { ...x, [k]: v } : x));
              return (
                <div key={i} className="card" style={{ padding: 12 }}>
                  <div className="row mb12"><span className="strong small">Failure {i + 1}</span><div className="spacer" />
                    {failures.length > 1 && <button className="btn ghost sm icon" aria-label="Remove failure" onClick={() => setFailures(failures.filter((_, j) => j !== i))}><LuTrash2 /></button>}</div>
                  <div className="col" style={{ gap: 10 }}>
                    <select className="select sm" aria-label="Target component" value={f.component_id} onChange={(e) => {
                      const c = compById[+e.target.value];
                      const okType = failureTypes.find((t) => t.type === f.failure_type);
                      const stillOk = !okType?.applicable_types || okType.applicable_types.includes(c?.component_type);
                      setFailures(failures.map((x, j) => j === i ? { ...x, component_id: +e.target.value, failure_type: stillOk ? x.failure_type : (c?.component_type === "DATABASE" ? "DATABASE_FAILURE" : "COMPLETE_SERVICE_FAILURE") } : x));
                    }}>
                      <option value="">Select component…</option>{comps.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    <select className="select sm" aria-label="Failure type" value={f.failure_type} onChange={(e) => upd("failure_type", e.target.value)}>
                      {allowed.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
                    </select>
                    {ft && <span className="faint xs">{ft.description}</span>}
                    <Field label={`Severity: ${f.severity}/10`}><input type="range" min={1} max={10} value={f.severity} onChange={(e) => upd("severity", +e.target.value)} /></Field>
                    <input className="input sm" placeholder="Failure description (optional)" value={f.description} onChange={(e) => upd("description", e.target.value)} />
                  </div>
                </div>
              );
            })}
            <button className="btn sm" onClick={() => setFailures([...failures, blankFailure()])}><LuPlus />Add simultaneous failure</button>
            <div className="divider" style={{ margin: 0 }} />
            <Field label="Simulation name"><input className="input" placeholder="e.g. Exam-day database outage" value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></Field>
            <Field label="Simulated failure duration (minutes)"><input className="input" type="number" min={1} value={meta.duration_minutes} onChange={(e) => setMeta({ ...meta, duration_minutes: +e.target.value })} /></Field>
            <Field label="Description"><textarea className="textarea" value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field>
            <div className="pill-tabs" role="radiogroup" aria-label="Execution mode">
              <button className={!instant ? "on" : ""} onClick={() => setInstant(false)}>Step-by-step</button>
              <button className={instant ? "on" : ""} onClick={() => setInstant(true)}>Instant</button>
            </div>
            <div className="row">
              <button className="btn primary" disabled={busy || !!active || !valid} onClick={createAndStart}><LuZap />Start simulation</button>
              <button className="btn" disabled={!valid} onClick={saveScenario}><LuSave />Save as scenario</button>
            </div>
            {sims.length > 0 && <button className="btn ghost sm" onClick={() => setMode("view")}>← Back to {selected?.name}</button>}
          </div>
        ) : sim && (
          <>
            <div className="side-section">
              <h2 className="ellipsis">{sim.name}</h2>
              <div className="faint xs mt8">#{sim.id} · created {fmtDate(sim.created_at)} · {sim.duration_minutes} min window</div>
              <div className="col mt12" style={{ gap: 6 }}>
                {sim.failures.map((f: any) => (
                  <div key={f.id} className="row small"><Badge value="SOURCE" /><span className="strong">{f.component_name}</span><span className="muted">{f.failure_label} · sev {f.severity}</span></div>
                ))}
              </div>
              {sim.status === "CREATED" && <Callout kind="info">Configured but not started yet. Press Start in the toolbar.</Callout>}
              {["PROPAGATED", "STOPPED"].includes(sim.status) && (
                <div className="col mt12" style={{ gap: 6 }}>
                  <Callout kind={sim.status === "STOPPED" ? "warn" : "info"}>{sim.status === "STOPPED" ? "Stopped before the cascade completed – analysis uses the revealed steps." : "Propagation complete. Continue with the analysis:"}</Callout>
                  <div className="grid g3" style={{ gap: 6 }}>
                    <button className="btn sm" onClick={() => navigate(`/projects/${pid}/impact?sim=${sim.id}`)}><LuGauge />Impact</button>
                    <button className="btn sm" onClick={() => navigate(`/projects/${pid}/root-cause?sim=${sim.id}`)}><LuSearch />Root cause</button>
                    <button className="btn sm primary" onClick={() => navigate(`/projects/${pid}/recovery?sim=${sim.id}`)}><LuWrench />Recover</button>
                  </div>
                </div>
              )}
              {["RECOVERING", "PARTIALLY_RECOVERED"].includes(sim.status) && <button className="btn sm mt12" onClick={() => navigate(`/projects/${pid}/execution?sim=${sim.id}`)}><LuFastForward />Open recovery execution</button>}
            </div>
            {nodeInfo && (
              <div className="side-section">
                <div className="row"><span className="strong">{nodeInfo.component_name}</span><div className="spacer" /><Badge value={revealed.has(nodeInfo.component_id) ? nodeInfo.status : "HEALTHY"} /></div>
                <div className="small muted mt8">{revealed.has(nodeInfo.component_id) ? (nodeInfo.reason || (nodeInfo.notes.length ? nodeInfo.notes.join(". ") : "Not affected by this failure.")) : "Not yet reached by the propagation."}</div>
                {nodeInfo.impact_type !== "UNAFFECTED" && revealed.has(nodeInfo.component_id) && <div className="xs faint mt8">Impact: {nodeInfo.impact_type.toLowerCase()} · depth {nodeInfo.depth}</div>}
              </div>
            )}
            <Tabs value={tab} onChange={setTab} tabs={[{ key: "sequence", label: "Propagation sequence" }, { key: "timeline", label: "Event timeline" }]} />
            {tab === "sequence" ? (
              <div className="side-section">
                {ticks.length === 0 && <span className="muted small">Nothing propagated yet.</span>}
                {ticks.map((t) => (
                  <div key={t} className="mb12">
                    <div className="section-title">Step {t} · {t === 0 ? "failure injected" : t === 1 ? "direct impact" : "indirect impact"}</div>
                    <div className="col" style={{ gap: 6 }}>{steps.filter((s) => s.tick === t).map((s) => (
                      <div key={s.component_id} className="step-row" style={{ cursor: "pointer" }} onClick={() => setSelectedNode(s.component_id)}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="row small"><span className="strong ellipsis">{s.name}</span><div className="spacer" /><Badge value={s.status} /><Badge value={s.impact_type} /></div>
                          <div className="faint xs mt8" style={{ marginTop: 4 }}>{s.reason}</div>
                        </div>
                      </div>
                    ))}</div>
                  </div>
                ))}
                {sim.status === "RUNNING" && sim.current_tick < sim.max_tick && <div className="row faint small"><span className="spinner" />Propagating…</div>}
              </div>
            ) : (
              <div className="side-section"><ActivityFeed items={[...timeline].reverse()} /></div>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
