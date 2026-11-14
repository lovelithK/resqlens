import { useState } from "react";
import { LuFileDown, LuFileSpreadsheet, LuGitCompare, LuHistory, LuTrash2 } from "react-icons/lu";
import { api, download, qs } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { navigate } from "../lib/router";
import { fmtDate, FAILURE_LABEL, minutes } from "../lib/format";
import { Badge, Card, Empty, Loading, Modal, PageHeader } from "../components/ui";

export default function HistoryPage() {
  const projects = useApi<any[]>("/projects");
  const [f, setF] = useState({ project_id: "", severity: "", status: "", date_from: "", date_to: "" });
  const query = qs(f);
  const sims = useApi<any[]>(`/simulations${query}`, [query]);
  const [picked, setPicked] = useState<number[]>([]);
  const [compare, setCompare] = useState<any[] | null>(null);
  const { error, confirm, toast } = useFeedback();
  const set = (k: string, v: string) => setF({ ...f, [k]: v });

  const runCompare = async () => {
    try { setCompare(await api.get(`/simulations/compare?ids=${picked.join(",")}`)); } catch (e) { error(e); }
  };
  const remove = async (s: any) => {
    if (!await confirm({ title: "Delete simulation record?", danger: true, message: `'${s.name}' and its results, plans and timeline will be deleted.` })) return;
    try { await api.del(`/simulations/${s.id}`); toast("success", "Simulation deleted"); sims.reload(); } catch (e) { error(e); }
  };
  return (
    <>
      <PageHeader title="Simulation History" description="Every simulation and recovery, stored with its scenario, impact and recovery results."
        actions={<>
          <button className="btn" disabled={picked.length < 2 || picked.length > 6} onClick={runCompare}><LuGitCompare />Compare ({picked.length})</button>
          <button className="btn" onClick={() => download(`/simulations/export.csv${query}`, "resqlens-simulation-history.csv").catch(error)}><LuFileSpreadsheet />Export CSV</button>
        </>} />
      <Card className="mb16">
        <div className="row wrap" style={{ gap: 12 }}>
          <select className="select" style={{ width: 240 }} aria-label="Project filter" value={f.project_id} onChange={(e) => set("project_id", e.target.value)}>
            <option value="">All projects</option>{(projects.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <select className="select" style={{ width: 160 }} aria-label="Severity filter" value={f.severity} onChange={(e) => set("severity", e.target.value)}>
            <option value="">Any severity</option>{["LOW", "MODERATE", "HIGH", "CRITICAL"].map((s) => <option key={s}>{s}</option>)}</select>
          <select className="select" style={{ width: 190 }} aria-label="Status filter" value={f.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any status</option>{["CREATED", "RUNNING", "PAUSED", "PROPAGATED", "STOPPED", "RECOVERING", "RECOVERED", "PARTIALLY_RECOVERED", "RESET"].map((s) => <option key={s} value={s}>{s.toLowerCase().replace("_", " ")}</option>)}</select>
          <label className="row small muted">From <input className="input" style={{ width: 160 }} type="date" value={f.date_from} onChange={(e) => set("date_from", e.target.value)} /></label>
          <label className="row small muted">To <input className="input" style={{ width: 160 }} type="date" value={f.date_to} onChange={(e) => set("date_to", e.target.value)} /></label>
          {Object.values(f).some(Boolean) && <button className="btn ghost sm" onClick={() => setF({ project_id: "", severity: "", status: "", date_from: "", date_to: "" })}>Clear filters</button>}
        </div>
      </Card>
      <Card bodyClass="">
        {sims.loading && !sims.data ? <Loading /> : !sims.data?.length ? <Empty icon={<LuHistory />} title="No simulations match">Adjust the filters or run a simulation.</Empty> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th style={{ width: 30 }} /><th>#</th><th>Simulation</th><th>Failure source</th><th>Type</th><th>Status</th><th className="right">Affected</th><th className="right">Impact</th><th>Strategy</th><th>Created</th><th /></tr></thead>
            <tbody>{sims.data.map((s) => (
              <tr key={s.id} className={picked.includes(s.id) ? "selected" : ""}>
                <td><input type="checkbox" aria-label={`Select ${s.name}`} checked={picked.includes(s.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, s.id] : picked.filter((x) => x !== s.id))} /></td>
                <td className="num faint">{s.id}</td>
                <td><a href="#" className="strong" onClick={(e) => { e.preventDefault(); navigate(`/projects/${s.project_id}/impact?sim=${s.id}`); }}>{s.name}</a><div className="faint xs">{s.project_name}</div></td>
                <td className="small">{s.failure_sources}</td><td className="small">{FAILURE_LABEL[s.failure_type]}</td>
                <td><Badge value={s.status} /></td><td className="right num">{s.affected_count}</td>
                <td className="right">{s.impact_score !== null ? <span className="row" style={{ justifyContent: "flex-end" }}><span className="num">{s.impact_score}</span><Badge value={s.severity_class} /></span> : "–"}</td>
                <td className="small muted">{s.selected_strategy || "–"}</td><td className="small muted nowrap">{fmtDate(s.created_at)}</td>
                <td className="nowrap">
                  <button className="btn ghost sm icon" title="Report" aria-label="Open report" onClick={() => navigate(`/reports?sim=${s.id}`)}><LuFileDown /></button>
                  <button className="btn ghost sm icon" title="Delete" aria-label="Delete simulation" onClick={() => remove(s)}><LuTrash2 /></button>
                </td>
              </tr>))}</tbody></table></div>
        )}
      </Card>
      {compare && (
        <Modal wide title="Scenario comparison" onClose={() => setCompare(null)}>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Metric</th>{compare.map((c) => <th key={c.id}>#{c.id} {c.name}</th>)}</tr></thead>
            <tbody>
              {[["Failure sources", (c: any) => c.sources.join(", ")], ["Failure type", (c: any) => FAILURE_LABEL[c.failure_type]],
                ["Affected components", (c: any) => c.affected_components ?? "–"], ["Impact score", (c: any) => c.impact_score ?? "–"],
                ["Severity", (c: any) => c.severity_class ? <Badge value={c.severity_class} /> : "–"],
                ["Critical functionality available", (c: any) => `${c.critical_functionality_available}/${c.critical_functionality_total}`],
                ["Strategy", (c: any) => c.strategy || "–"], ["Estimated recovery", (c: any) => minutes(c.estimated_minutes)],
                ["Actual simulated recovery", (c: any) => minutes(c.actual_minutes)], ["Recovery cost", (c: any) => c.recovery_cost ?? "–"],
                ["Status", (c: any) => <Badge value={c.status} />]].map(([label, fn]: any) => (
                <tr key={label}><td className="muted">{label}</td>{compare.map((c) => <td key={c.id}>{fn(c)}</td>)}</tr>))}
            </tbody></table></div>
        </Modal>
      )}
    </>
  );
}
