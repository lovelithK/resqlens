import { useState } from "react";
import {
  LuDownload, LuGauge, LuGitCompare, LuNetwork, LuPencil, LuPlay, LuSearch, LuShieldCheck, LuTriangleAlert, LuWrench, LuZap,
} from "react-icons/lu";
import { api, download } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { navigate } from "../lib/router";
import { STATUS_COLOR } from "../lib/format";
import GraphCanvas from "../components/GraphCanvas";
import { Badge, Callout, Card, Loading, PageHeader, Stat } from "../components/ui";
import { ProjectForm } from "./Projects";
import { ActivityFeed } from "./Dashboard";

const MODULES = [
  ["architecture", LuNetwork, "Architecture Builder", "Model components, dependencies, backups and functionalities."],
  ["simulation", LuZap, "Failure Simulation", "Inject failures and watch the cascade step by step."],
  ["impact", LuGauge, "Impact Analysis", "Weighted impact score, affected functionality and propagation paths."],
  ["root-cause", LuSearch, "Root Cause Analysis", "Verified vs inferred causes, traces and symptom diagnosis."],
  ["recovery", LuWrench, "Recovery Planner", "Compare four strategies with rule-based explanations."],
  ["execution", LuPlay, "Recovery Execution", "Execute the plan step by step with dependency validation."],
  ["resilience", LuShieldCheck, "Resilience Analytics", "Transparent score, SPOFs and mitigations."],
  ["what-if", LuGitCompare, "What-If Scenarios", "Compare hypothetical failure scenarios side by side."],
] as const;

export default function WorkspacePage({ pid }: { pid: number }) {
  const arch = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const activity = useApi<any[]>(`/activity?project_id=${pid}&limit=12`, [pid]);
  const { toast, error } = useFeedback();
  const [editing, setEditing] = useState(false);
  if (arch.loading && !arch.data) return <Loading />;
  if (arch.error || !arch.data) return <Callout kind="error">{arch.error?.message || "Project not found"}</Callout>;
  const a = arch.data;
  const p = a.project;
  const v = a.validation;
  const counts: Record<string, number> = {};
  a.components.forEach((c: any) => { counts[c.status] = (counts[c.status] || 0) + 1; });

  const save = async (form: any) => {
    try { await api.put(`/projects/${pid}`, form); toast("success", "Project updated"); setEditing(false); arch.reload(); } catch (e) { error(e); }
  };
  return (
    <>
      <PageHeader title={p.name} description={p.description || "No description"} actions={<>
        <button className="btn" onClick={() => setEditing(true)}><LuPencil />Edit</button>
        <button className="btn" onClick={() => download(`/projects/${pid}/export`, `${p.name.replace(/\W+/g, "-").toLowerCase()}.json`).catch(error)}><LuDownload />Export JSON</button>
        <button className="btn primary" onClick={() => navigate(`/projects/${pid}/simulation`)}><LuZap />Simulate failure</button>
      </>} />
      {a.active_simulation && (
        <div className="banner"><LuTriangleAlert color="var(--failed)" />
          <span>Simulation <b>{a.active_simulation.name}</b> is {a.active_simulation.status.toLowerCase()}. The architecture is locked until it is reset or fully recovered.</span>
          <div className="spacer" />
          <button className="btn sm" onClick={() => navigate(`/projects/${pid}/simulation?sim=${a.active_simulation.id}`)}>Open simulation</button>
        </div>
      )}
      <div className="grid g-stats mb16">
        <Stat label="Components" value={a.stats.component_count} hint={Object.entries(counts).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(" · ")} />
        <Stat label="Dependencies" value={a.stats.dependency_count} hint={`${a.stats.mandatory_dependency_count} mandatory · ${a.stats.optional_dependency_count} optional`} />
        <Stat label="Configured backups" value={a.stats.fallback_count} />
        <Stat label="Functionalities" value={a.stats.functionality_count} />
        <Stat label="Max dependency depth" value={a.stats.max_depth} />
        <Stat label="Validation" value={v.valid ? "Valid" : `${v.error_count} error(s)`} color={v.valid ? "var(--healthy)" : "var(--failed)"} hint={`${v.warning_count} warning(s) · policy ${p.propagation_policy.toLowerCase().replace("_", "-")}`} />
      </div>
      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <Card title="Architecture" sub="Live simulated state" bodyClass="" actions={<button className="btn sm" onClick={() => navigate(`/projects/${pid}/architecture`)}><LuNetwork />Open builder</button>}>
            <div style={{ height: 380, display: "flex" }}>
              {a.components.length ? <GraphCanvas nodes={a.components} edges={a.dependencies} showLegend={false}
                onSelectNode={(id) => id && navigate(`/projects/${pid}/architecture?select=${id}`)} />
                : <div className="empty w100"><h3>Empty architecture</h3><button className="btn primary" onClick={() => navigate(`/projects/${pid}/architecture`)}>Add components</button></div>}
            </div>
          </Card>
          <div className="grid g2">
            {MODULES.map(([slug, Icon, label, desc]) => (
              <div key={slug} className="card hoverable" style={{ cursor: "pointer" }} onClick={() => navigate(`/projects/${pid}/${slug}`)}>
                <div className="card-body row" style={{ alignItems: "flex-start", gap: 12 }}>
                  <div style={{ width: 34, height: 34, borderRadius: 8, background: "var(--accent-soft)", display: "grid", placeItems: "center", flex: "none" }}><Icon color="#93c5fd" /></div>
                  <div><h3>{label}</h3><p className="muted small mt8" style={{ marginTop: 3 }}>{desc}</p></div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="col" style={{ gap: 14 }}>
          <Card title="Validation" sub="Cycle detection, missing/duplicate dependencies, backups">
            {v.issues.length === 0 ? <Callout kind="success">No issues found. The dependency graph is acyclic and consistent.</Callout> : (
              <div className="col" style={{ gap: 8 }}>{v.issues.map((i: any, idx: number) => (
                <div key={idx} className="row small" style={{ alignItems: "flex-start" }}><Badge value={i.level} /><span>{i.message}</span></div>
              ))}</div>
            )}
          </Card>
          <Card title="Functionalities" sub="User-facing features and their availability">
            <div className="col" style={{ gap: 8 }}>
              {a.functionalities.map((f: any) => {
                const down = f.component_ids.some((id: number) => ["FAILED", "BLOCKED", "RECOVERING"].includes(a.components.find((c: any) => c.id === id)?.status));
                return <div key={f.id} className="row small"><span className="dotline" style={{ background: down ? STATUS_COLOR.FAILED : STATUS_COLOR.HEALTHY }} /><span className="strong">{f.name}</span>{f.is_critical && <Badge value="CRITICAL" label="critical" />}<div className="spacer" /><span className="faint xs">{f.component_ids.length} components</span></div>;
              })}
              {!a.functionalities.length && <span className="muted small">No functionalities defined. Add them in the Architecture Builder to measure user-facing impact.</span>}
            </div>
          </Card>
          <Card title="Project activity"><ActivityFeed items={activity.data || []} /></Card>
        </div>
      </div>
      {editing && <ProjectForm title="Edit project" initial={p} onClose={() => setEditing(false)} onSubmit={save} />}
    </>
  );
}
