import { useEffect, useMemo, useState } from "react";
import { LuCircleCheck, LuCircleX, LuClock, LuFastForward, LuPause, LuPlay, LuRefreshCw, LuRotateCcw, LuShieldCheck, LuStepForward } from "react-icons/lu";
import { api } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi, useInterval } from "../lib/hooks";
import { navigate, useQueryParam } from "../lib/router";
import { minutes } from "../lib/format";
import GraphCanvas from "../components/GraphCanvas";
import { SimSelector, useProjectSimulation } from "../components/SimSelector";
import { Badge, Callout, Empty, Loading, Progress } from "../components/ui";
import { Explanation } from "./RecoveryPlanner";

export default function ExecutionPage({ pid }: { pid: number }) {
  const { sims, selected, select, loading } = useProjectSimulation(pid);
  const arch = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const plans = useApi<any>(selected ? `/simulations/${selected.id}/recovery-plans` : null, [selected?.id]);
  const [planParam, setPlanParam] = useQueryParam("plan");
  const [plan, setPlan] = useState<any>(null);
  const [auto, setAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const { error, notify, confirm, toast } = useFeedback();

  const list: any[] = (plans.data?.plans || []).filter((p: any) => p.status !== "SUPERSEDED");
  const chosen = list.find((p) => String(p.id) === planParam) || list.find((p) => ["EXECUTING", "PAUSED"].includes(p.status)) || list.find((p) => p.is_selected) || list[0];
  useEffect(() => { if (chosen) api.get(`/recovery-plans/${chosen.id}`).then(setPlan).catch(error); else setPlan(null); }, [chosen?.id, plans.data]);

  const apply = (p: any) => { setPlan(p); notify(p.notifications); arch.reload(); };
  const act = async (path: string, body?: any) => {
    if (!plan) return;
    setBusy(true);
    try { apply(await api.post(`/recovery-plans/${plan.id}/${path}`, body ?? {})); if (path !== "step") plans.reload(); }
    catch (e) { error(e); setAuto(false); } finally { setBusy(false); }
  };
  useInterval(() => { if (!busy) act("step"); }, 900, !!plan && plan.status === "EXECUTING" && auto);
  useEffect(() => { if (plan && ["COMPLETED", "COMPLETED_WITH_FAILURES"].includes(plan.status)) plans.reload(); }, [plan?.status]);

  const badges = useMemo(() => {
    const b: Record<number, string> = {};
    (plan?.actions || []).filter((a: any) => a.status === "PENDING").sort((a: any, b2: any) => a.order_index - b2.order_index)
      .forEach((a: any, i: number) => { if (a.component_id) b[a.component_id] = String(i + 1); });
    return b;
  }, [plan]);

  if (loading || (arch.loading && !arch.data)) return <Loading />;
  if (!selected) return <div className="content"><Empty title="No simulation yet" action={<button className="btn primary" onClick={() => navigate(`/projects/${pid}/simulation`)}>Run a simulation</button>} /></div>;

  const acts: any[] = plan ? [...plan.actions].sort((a, b) => a.order_index - b.order_index) : [];
  const done = acts.filter((a) => a.status !== "PENDING").length;
  const pendingFirst = acts.find((a) => a.status === "PENDING");
  const s = plan?.summary;
  const finished = plan && ["COMPLETED", "COMPLETED_WITH_FAILURES"].includes(plan.status);
  const reset = async () => {
    if (!await confirm({ title: "Reset simulation?", message: "Restore every component to its baseline and close this simulation." })) return;
    try { await api.post(`/simulations/${selected.id}/reset`); toast("success", "Architecture reset"); arch.reload(); plans.reload(); } catch (e) { error(e); }
  };

  return (
    <div className="split">
      <div className="center">
        <div className="toolbar">
          <SimSelector sims={sims} selected={selected} onSelect={(id) => { setPlanParam(null); select(id); }} />
          {list.length > 0 && <select className="select sm" style={{ width: 250 }} aria-label="Recovery plan" value={plan?.id || ""} onChange={(e) => setPlanParam(e.target.value)}>
            {list.map((p) => <option key={p.id} value={p.id}>{p.strategy.name}{p.is_manual ? " (manual)" : ""} · {p.status.toLowerCase()}</option>)}
          </select>}
          {plan && <Badge value={plan.status} dot />}
          <div className="spacer" />
          {plan?.status === "DRAFT" && <>
            <button className="btn sm primary" disabled={busy} onClick={() => act("execute")}><LuPlay />Start recovery</button>
            <button className="btn sm" disabled={busy} onClick={() => act("execute", { run_to_completion: true })}><LuFastForward />Run instantly</button>
          </>}
          {plan?.status === "EXECUTING" && <>
            <label className="check xs"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />Auto-step</label>
            <button className="btn sm" disabled={busy} onClick={() => act("step")}><LuStepForward />Step</button>
            <button className="btn sm" disabled={busy} onClick={() => act("pause")}><LuPause />Pause</button>
          </>}
          {plan?.status === "PAUSED" && <button className="btn sm" disabled={busy} onClick={() => { setAuto(true); act("resume"); }}><LuPlay />Resume</button>}
          {selected.status === "PARTIALLY_RECOVERED" && <button className="btn sm" onClick={() => navigate(`/projects/${pid}/recovery?sim=${selected.id}`)}><LuRefreshCw />New plan for remaining</button>}
          {["PARTIALLY_RECOVERED", "PROPAGATED", "STOPPED"].includes(selected.status) && <button className="btn sm" onClick={reset}><LuRotateCcw />Reset</button>}
        </div>
        {plan && <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", background: "var(--bg-2)" }}>
          <div className="row small"><span className="muted">Progress</span><span className="num strong">{done}/{acts.length}</span><span className="faint">actions processed</span><div className="spacer" />
            <LuClock size={14} className="muted" /><span className="muted">Simulated clock</span><span className="num strong">{minutes(plan.sim_clock)}</span><span className="faint">/ est. {minutes(plan.estimated_minutes)}</span></div>
          <div className="mt8"><Progress value={acts.length ? done / acts.length : 0} color={finished ? (plan.status === "COMPLETED" ? "var(--healthy)" : "var(--degraded)") : "var(--recovering)"} /></div>
        </div>}
        <GraphCanvas nodes={arch.data?.components || []} edges={arch.data?.dependencies || []} badges={badges}
          selectedId={pendingFirst?.component_id} onSelectNode={(id) => { const a = acts.find((x) => x.component_id === id); if (a) setOpenId(a.id); }} />
      </div>
      <aside className="side" aria-label="Recovery execution">
        {!list.length ? (
          <div className="side-section"><Empty title="No recovery plan" action={<button className="btn primary" onClick={() => navigate(`/projects/${pid}/recovery?sim=${selected.id}`)}>Open recovery planner</button>}>Generate and select a plan first.</Empty></div>
        ) : !plan ? <Loading /> : (
          <>
            {finished && s && (
              <div className="side-section">
                <Callout kind={plan.status === "COMPLETED" ? "success" : "warn"}>
                  {plan.status === "COMPLETED" ? "System recovered. All components are back to their baseline state." : `Recovery finished with ${s.actions_failed} failed action(s). Still unhealthy: ${s.still_unhealthy.join(", ") || "–"}.`}
                </Callout>
                <div className="grid g2 mt12 small">
                  <div><div className="faint xs">Actions completed</div><div className="strong num">{s.actions_completed}/{s.actions_total}</div></div>
                  <div><div className="faint xs">Retried / failed</div><div className="strong num">{s.retried_actions} / {s.actions_failed}</div></div>
                  <div><div className="faint xs">Estimated vs actual</div><div className="strong num">{minutes(s.estimated_minutes)} / {minutes(s.actual_minutes)}</div></div>
                  <div><div className="faint xs">Health before → after</div><div className="strong num">{s.health_before}% → {s.health_after}%</div></div>
                  <div><div className="faint xs">Functionality available</div><div className="strong num">{s.functionalities_available}/{s.functionalities_total}</div></div>
                </div>
                <div className="row mt12">
                  <button className="btn sm" onClick={() => navigate(`/projects/${pid}/resilience`)}><LuShieldCheck />Resilience score</button>
                  <button className="btn sm" onClick={() => navigate(`/reports?sim=${selected.id}`)}>Open report</button>
                </div>
              </div>
            )}
            {plan.status === "DRAFT" && <div className="side-section"><Callout>Before restoring each component the simulator checks that its required dependencies are available. Failed actions are re-queued once at the end of the plan.</Callout></div>}
            <div className="side-section">
              <div className="section-title">Recovery sequence · {plan.strategy.name}</div>
              <div className="col" style={{ gap: 8 }}>
                {acts.map((a, i) => {
                  const cls = a.status === "COMPLETED" ? "done" : a.status === "FAILED" ? "failed" : pendingFirst?.id === a.id && plan.status !== "DRAFT" ? "current" : "";
                  return (
                    <div key={a.id} className={`step-row ${cls}`} style={{ cursor: "pointer" }} onClick={() => setOpenId(openId === a.id ? null : a.id)}>
                      <div className="step-num">{a.status === "COMPLETED" ? <LuCircleCheck color="var(--healthy)" /> : a.status === "FAILED" ? <LuCircleX color="var(--failed)" /> : i + 1}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="row small"><span className="strong ellipsis">{a.component_name}</span><div className="spacer" />
                          {a.attempts > 0 && a.status === "PENDING" ? <Badge value="WARNING" label="retry queued" /> : <Badge value={a.status === "PENDING" ? "INFO" : a.status} label={a.status.toLowerCase()} />}</div>
                        <div className="muted xs">{a.action_label} · est. {minutes(a.estimated_minutes)}{a.sim_end_minute !== null && ` · ended at minute ${a.sim_end_minute}`}</div>
                        {a.failure_reason && <div className="xs" style={{ color: "#ffaaa6", marginTop: 3 }}>{a.failure_reason}</div>}
                        {openId === a.id && <Explanation e={a.explanation} />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
