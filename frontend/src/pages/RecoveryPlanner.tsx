import { useEffect, useMemo, useState } from "react";
import { LuArrowDown, LuArrowUp, LuCheck, LuChevronDown, LuChevronRight, LuPlay, LuRefreshCw, LuSave, LuWrench } from "react-icons/lu";
import { api } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { navigate } from "../lib/router";
import { minutes } from "../lib/format";
import { SimSelector, useProjectSimulation } from "../components/SimSelector";
import { Badge, Callout, Card, Empty, Loading, PageHeader } from "../components/ui";
import { BarChart, LineChart } from "../components/charts";
import { NoSimulation } from "./Impact";

const COLORS = ["#3b82f6", "#22d3ee", "#a78bfa", "#f59e0b"];
const PLANNABLE = ["PROPAGATED", "STOPPED", "PARTIALLY_RECOVERED"];

export function Explanation({ e }: { e: any }) {
  return (
    <dl className="explain">
      <dt>What</dt><dd>{e.what}</dd>
      <dt>Why</dt><dd>{e.why}</dd>
      <dt>Dependencies</dt><dd>{e.dependencies}</dd>
      <dt>If skipped</dt><dd>{e.if_skipped}</dd>
      <dt>Expected benefit</dt><dd>{e.benefit}</dd>
      {e.strategy_rationale && <><dt>Order rationale</dt><dd>{e.strategy_rationale}</dd></>}
    </dl>
  );
}

export default function RecoveryPlannerPage({ pid }: { pid: number }) {
  const { sims, selected, select, loading } = useProjectSimulation(pid);
  const plans = useApi<any>(selected ? `/simulations/${selected.id}/recovery-plans` : null, [selected?.id]);
  const { toast, error, notify } = useFeedback();
  const [viewId, setViewId] = useState<number | null>(null);
  const [order, setOrder] = useState<any[] | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [violations, setViolations] = useState<any[]>([]);
  const [allowInvalid, setAllowInvalid] = useState(false);
  const [busy, setBusy] = useState(false);

  const list: any[] = (plans.data?.plans || []).filter((p: any) => p.status !== "SUPERSEDED");
  const drafts = list.filter((p) => p.status === "DRAFT");
  const view = list.find((p) => p.id === viewId) || list.find((p) => p.is_selected) || drafts[0] || list[list.length - 1];
  useEffect(() => { setOrder(null); setViolations([]); }, [view?.id]);
  const simStatus = plans.data?.simulation_status;

  const generate = async () => {
    setBusy(true);
    try { const r = await api.post(`/simulations/${selected!.id}/recovery-plans`, {}); notify(r.notifications); plans.reload(); setViewId(null); toast("success", "Generated plans for all four strategies"); }
    catch (e) { error(e); } finally { setBusy(false); }
  };
  const selectPlan = async (id: number) => {
    try { await api.post(`/recovery-plans/${id}/select`); plans.reload(); setViewId(id); toast("success", "Strategy selected"); } catch (e) { error(e); }
  };
  const move = (i: number, d: number) => {
    const cur = [...(order || [...view.actions].sort((a, b) => a.order_index - b.order_index))];
    const j = i + d;
    if (j < 0 || j >= cur.length) return;
    [cur[i], cur[j]] = [cur[j], cur[i]];
    setOrder(cur);
    setViolations([]);
  };
  const saveOrder = async () => {
    try {
      await api.put(`/recovery-plans/${view.id}/sequence`, { component_order: order!.map((a) => a.component_id), allow_invalid: allowInvalid });
      toast(allowInvalid ? "warning" : "success", allowInvalid ? "Saved manual sequence (validation bypassed – execution will check dependencies)" : "Manual sequence validated and saved");
      setOrder(null); setViolations([]); plans.reload();
    } catch (e: any) {
      if (e.code === "INVALID_RECOVERY_SEQUENCE") { setViolations(e.details || []); toast("error", e.message); } else error(e);
    }
  };

  const series = useMemo(() => drafts.map((p, i) => ({
    name: p.strategy.name, color: COLORS[i % 4],
    points: (p.metrics.timeline || []).map((t: any) => ({ x: t.minute, y: t.available_functionalities })),
  })), [plans.data]);

  if (loading) return <Loading />;
  const header = <PageHeader title="Recovery Planner" description="Four interchangeable strategies (Strategy pattern) over the same dependency-constrained scheduler. Every recommendation is explained by rules."
    actions={<><SimSelector sims={sims} selected={selected} onSelect={select} />
      {selected && PLANNABLE.includes(simStatus) && <button className="btn primary" disabled={busy} onClick={generate}><LuRefreshCw />{drafts.length ? "Regenerate plans" : "Generate plans"}</button>}</>} />;
  if (!selected) return <>{header}<NoSimulation pid={pid} /></>;
  if (plans.loading && !plans.data) return <>{header}<Loading /></>;

  const actions = order || (view ? [...view.actions].sort((a: any, b: any) => a.order_index - b.order_index) : []);
  const editable = view?.status === "DRAFT";
  return (
    <>
      {header}
      {!PLANNABLE.includes(simStatus) && !list.length && (
        <Callout kind="info">{["RUNNING", "PAUSED"].includes(simStatus) ? "The simulation is still propagating. Plans can be generated when propagation completes or is stopped." : simStatus === "RESET" ? "This simulation has been reset – its live state no longer exists, so no new plan can be generated." : `Simulation is ${simStatus?.toLowerCase()}.`}</Callout>
      )}
      {!list.length && PLANNABLE.includes(simStatus) && (
        <Card><Empty icon={<LuWrench />} title="No recovery plans yet" action={<button className="btn primary" disabled={busy} onClick={generate}><LuRefreshCw />Generate plans</button>}>
          ResQLens builds one plan per strategy from the actual dependency relationships and configured recovery times.</Empty></Card>
      )}
      {list.length > 0 && (
        <>
          <Card title="Strategy comparison" sub="Sequential execution: total time and cost are equal for complete plans; strategies differ in how fast functionality returns." bodyClass="">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Strategy</th><th className="right">Actions</th><th className="right">Total time</th><th className="right">Cost</th><th className="right">Functionality downtime*</th><th className="right">Critical restored at</th><th className="right">Mean restore</th><th>Status</th><th /></tr></thead>
              <tbody>{list.map((p) => {
                const dts = drafts.map((x) => x.metrics.functionality_downtime_minutes);
                const best = drafts.length > 1 && new Set(dts).size > 1 && p.metrics.functionality_downtime_minutes === Math.min(...dts);
                return (
                  <tr key={p.id} className={`clickable ${view?.id === p.id ? "selected" : ""}`} onClick={() => setViewId(p.id)}>
                    <td><div className="strong">{p.strategy.name}</div>{p.is_manual && <span className="faint xs">manually modified{!p.is_valid && " · invalid order"}</span>}</td>
                    <td className="right num">{p.actions.length}</td><td className="right num">{minutes(p.estimated_minutes)}</td><td className="right num">{p.total_cost}</td>
                    <td className="right num">{p.metrics.functionality_downtime_minutes}{best && <span style={{ color: "var(--healthy)" }}> ★</span>}</td>
                    <td className="right num">{minutes(p.metrics.critical_functionality_restored_at)}</td><td className="right num">{minutes(p.metrics.mean_component_restore_minute)}</td>
                    <td>{p.is_selected ? <Badge value="RECOVERING" label="selected" /> : <Badge value={p.status} />}</td>
                    <td onClick={(e) => e.stopPropagation()}>{p.status === "DRAFT" && !p.is_selected && <button className="btn sm" onClick={() => selectPlan(p.id)}><LuCheck />Select</button>}</td>
                  </tr>);
              })}</tbody></table></div>
            <div className="faint xs" style={{ padding: "8px 14px" }}>* Sum over affected functionalities of the simulated minute at which each becomes available again (lower is better). ★ = lowest among current drafts. No strategy is claimed to be globally optimal.</div>
          </Card>

          {drafts.length > 1 && (
            <div className="grid g2 mt16">
              <Card title="Functionality downtime by strategy"><BarChart data={drafts.map((p, i) => ({ label: p.strategy.name.replace(" Recovery", "").replace("Maximum ", "Max "), value: p.metrics.functionality_downtime_minutes, color: COLORS[i % 4] }))} /></Card>
              <Card title="Available functionalities over simulated time"><LineChart series={series} step xLabel="minutes" yMax={Math.max(1, ...series.flatMap((s) => s.points.map((p: any) => p.y)))} /></Card>
            </div>
          )}

          {view && (
            <Card className="mt16" title={<>{view.strategy.name}{view.is_manual && <span className="muted"> · manual</span>}</>} sub={view.strategy.description}
              actions={<>{editable && !view.is_selected && <button className="btn sm" onClick={() => selectPlan(view.id)}><LuCheck />Select</button>}
                <button className="btn sm primary" onClick={() => navigate(`/projects/${pid}/execution?sim=${selected.id}&plan=${view.id}`)}><LuPlay />{view.status === "DRAFT" ? "Execute this plan" : "View execution"}</button></>}>
              <Callout>{view.strategy.guarantee}</Callout>
              {!view.is_valid && <Callout kind="warn">This manually ordered plan violates dependency rules. Execution will validate dependencies at each step; affected actions fail and are retried once.</Callout>}
              {editable && <p className="muted small mt12">Reorder actions with the arrows to build a manual sequence, then save it – the server validates it against the mandatory dependencies.</p>}
              {violations.length > 0 && <div className="callout error mt12"><div>{violations.map((v, i) => <div key={i}>{v.message}</div>)}</div></div>}
              <div className="col mt12" style={{ gap: 8 }}>
                {actions.map((a: any, i: number) => (
                  <div key={a.component_id} className="step-row">
                    <div className="step-num">{i + 1}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row small" style={{ cursor: "pointer" }} onClick={() => { const s = new Set(open); s.has(a.component_id) ? s.delete(a.component_id) : s.add(a.component_id); setOpen(s); }}>
                        {open.has(a.component_id) ? <LuChevronDown /> : <LuChevronRight />}
                        <span className="strong">{a.action_label}</span><span className="muted">on</span><span className="strong">{a.component_name}</span>
                        <div className="spacer" /><span className="faint xs num">{minutes(a.estimated_minutes)} · cost {a.cost}</span>
                      </div>
                      {!open.has(a.component_id) && a.explanation.benefit && <div className="faint xs" style={{ marginTop: 3, paddingLeft: 22 }}>{a.explanation.benefit}</div>}
                      {open.has(a.component_id) && <div style={{ paddingLeft: 22 }}><Explanation e={a.explanation} /></div>}
                    </div>
                    {editable && <div className="col" style={{ gap: 2 }}>
                      <button className="btn ghost sm icon" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}><LuArrowUp /></button>
                      <button className="btn ghost sm icon" aria-label="Move down" disabled={i === actions.length - 1} onClick={() => move(i, 1)}><LuArrowDown /></button>
                    </div>}
                  </div>
                ))}
              </div>
              {order && (
                <div className="row mt12">
                  <button className="btn primary sm" onClick={saveOrder}><LuSave />Save manual sequence</button>
                  <button className="btn sm" onClick={() => { setOrder(null); setViolations([]); }}>Discard</button>
                  <label className="check small"><input type="checkbox" checked={allowInvalid} onChange={(e) => setAllowInvalid(e.target.checked)} />Allow invalid order (to test execution-time validation)</label>
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </>
  );
}
