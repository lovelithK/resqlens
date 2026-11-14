import {
  LuActivity, LuCircleCheck, LuFolderKanban, LuFolderPlus, LuHistory, LuNetwork, LuServer, LuShieldCheck, LuTriangleAlert,
  LuWrench, LuZap, LuCircleX,
} from "react-icons/lu";
import { useApi } from "../lib/hooks";
import { Link, navigate } from "../lib/router";
import { ago, FAILURE_LABEL, STATUS_COLOR, scoreColor } from "../lib/format";
import { Badge, Card, Empty, HealthBar, Loading, PageHeader, Stat, Callout } from "../components/ui";
import { Donut, Gauge } from "../components/charts";

export function eventLevel(type: string) {
  if (["FAILURE_INJECTED", "RECOVERY_ACTION_FAILED"].includes(type)) return "error";
  if (["DEPENDENCY_AFFECTED", "FAILURE_PROPAGATED", "PROPAGATION_COMPLETED", "RECOVERY_INCOMPLETE", "SIMULATION_STOPPED"].includes(type)) return "warn";
  if (["COMPONENT_RESTORED", "SYSTEM_RECOVERED"].includes(type)) return "success";
  return "info";
}

export function ActivityFeed({ items }: { items: any[] }) {
  if (!items.length) return <Empty title="No activity yet">Create a project or run a simulation to see activity here.</Empty>;
  return (
    <div className="timeline">
      {items.map((e) => (
        <div key={e.id} className={`tl-item ${eventLevel(e.event_type)}`}>
          <div className="row" style={{ gap: 8 }}><span className="tl-type">{e.event_type.replace(/_/g, " ")}</span><span className="tl-time">{ago(e.created_at)}</span></div>
          <div className="tl-msg">{e.message}</div>
          {e.project_name && <div className="faint xs">{e.project_name}</div>}
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data, loading, error } = useApi<any>("/dashboard");
  if (loading && !data) return <Loading />;
  if (error || !data) return <Callout kind="error">{error?.message || "Could not load the dashboard."}</Callout>;
  const t = data.totals;
  const dist = data.status_distribution;
  const firstProject = data.projects[0];
  return (
    <>
      <PageHeader title="Dashboard" description="Live overview generated from your projects, simulations and recovery records."
        actions={<>
          <button className="btn" onClick={() => navigate("/projects?new=1")}><LuFolderPlus />New project</button>
          {firstProject && <button className="btn primary" onClick={() => navigate(`/projects/${firstProject.id}/simulation`)}><LuZap />Run simulation</button>}
        </>} />

      {t.active_incidents > 0 && (
        <div className="banner"><LuTriangleAlert color="var(--failed)" />
          <span><b>{t.active_incidents}</b> simulated incident(s) active · {t.failed_components} component(s) failed or blocked.</span>
          <div className="spacer" />
          {data.projects.filter((p: any) => p.active_simulation).slice(0, 1).map((p: any) => (
            <button key={p.id} className="btn sm" onClick={() => navigate(`/projects/${p.id}/simulation`)}>Open {p.name.length > 28 ? "project" : p.name}</button>
          ))}
        </div>
      )}

      <div className="grid g-stats mb16">
        <Stat label="Projects" icon={<LuFolderKanban size={14} />} value={t.projects} hint={`${t.simulations} simulation(s) run`} />
        <Stat label="System components" icon={<LuServer size={14} />} value={t.components} />
        <Stat label="Active incidents" icon={<LuZap size={14} />} value={t.active_incidents} color={t.active_incidents ? "var(--failed)" : undefined} hint="Simulated, not production" />
        <Stat label="Failed / blocked" icon={<LuCircleX size={14} />} value={t.failed_components} color={t.failed_components ? "var(--failed)" : undefined} hint={`${t.degraded_components} degraded`} />
        <Stat label="Healthy components" icon={<LuCircleCheck size={14} />} value={t.healthy_components} color="var(--healthy)" />
        <Stat label="Recovery operations" icon={<LuWrench size={14} />} value={t.recovery_operations} hint={`${t.successful_recoveries} fully successful · ${t.recovery_actions_completed} actions`} />
      </div>

      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <Card title="System health overview" sub="Per-project live health (criticality-weighted) and resilience" icon={<LuActivity />}>
            {data.projects.length === 0 ? (
              <Empty title="No projects yet" action={<button className="btn primary" onClick={() => navigate("/projects?new=1")}><LuFolderPlus />Create project</button>}>
                Model your first architecture to start simulating failures.
              </Empty>
            ) : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Project</th><th>Components</th><th style={{ width: 180 }}>Health</th><th>Resilience</th><th>SPOFs</th><th>Simulation</th></tr></thead>
                <tbody>{data.projects.map((p: any) => (
                  <tr key={p.id} className="clickable" onClick={() => navigate(`/projects/${p.id}`)}>
                    <td className="strong">{p.name}</td>
                    <td className="num">{p.component_count}{p.failed_count ? <span className="sev-CRITICAL"> · {p.failed_count} down</span> : null}</td>
                    <td><HealthBar value={p.current_health} /></td>
                    <td>{p.resilience_score !== null ? <span className="num strong" style={{ color: scoreColor(p.resilience_score) }}>{p.resilience_score} <span className="muted">({p.resilience_grade})</span></span> : "–"}</td>
                    <td className="num">{p.spof_count}</td>
                    <td>{p.active_simulation ? <Badge value="RUNNING" label={p.active_simulation} dot /> : <span className="faint">idle</span>}</td>
                  </tr>))}
                </tbody></table></div>
            )}
          </Card>

          <Card title="Recent simulations" icon={<LuHistory />} actions={<Link to="/history" className="small">View all</Link>} bodyClass="">
            {data.recent_simulations.length === 0 ? <Empty title="No simulations yet">Run one of the predefined scenarios from a project's Failure Simulation page.</Empty> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Simulation</th><th>Failure</th><th>Status</th><th className="right">Impact</th><th>When</th></tr></thead>
                <tbody>{data.recent_simulations.map((s: any) => (
                  <tr key={s.id} className="clickable" onClick={() => navigate(`/projects/${s.project_id}/impact?sim=${s.id}`)}>
                    <td><div className="strong">{s.name}</div><div className="faint xs">{s.project_name}</div></td>
                    <td className="small">{FAILURE_LABEL[s.failure_type]}<div className="faint xs">{s.failure_sources}</div></td>
                    <td><Badge value={s.status} /></td>
                    <td className="right">{s.impact_score !== null ? <span className="row" style={{ justifyContent: "flex-end" }}><span className="num strong">{s.impact_score}</span><Badge value={s.severity_class} /></span> : "–"}</td>
                    <td className="muted small nowrap">{ago(s.created_at)}</td>
                  </tr>))}</tbody></table></div>
            )}
          </Card>
        </div>

        <div className="col" style={{ gap: 14 }}>
          <Card title="Overall resilience" icon={<LuShieldCheck />} sub="Mean of each project's transparent resilience score">
            <div className="row" style={{ gap: 18 }}>
              <Gauge value={t.resilience_score} label="resilience" />
              <div className="col small" style={{ gap: 6 }}>
                <span className="muted">Scores combine single points of failure, blast radius, redundancy, live health and recovery efficiency.</span>
                {firstProject && <Link to={`/projects/${firstProject.id}/resilience`}>See score breakdown →</Link>}
              </div>
            </div>
          </Card>
          <Card title="Component status" sub="All projects, live simulated state">
            <Donut data={Object.entries(dist).map(([k, v]) => ({ label: k.toLowerCase(), value: v as number, color: STATUS_COLOR[k] }))} />
          </Card>
          <Card title="Quick actions">
            <div className="grid g2">
              <button className="btn" onClick={() => navigate("/projects?new=1")}><LuFolderPlus />New project</button>
              <button className="btn" disabled={!firstProject} onClick={() => navigate(`/projects/${firstProject.id}/architecture`)}><LuNetwork />Edit architecture</button>
              <button className="btn" disabled={!firstProject} onClick={() => navigate(`/projects/${firstProject.id}/simulation`)}><LuZap />Simulate failure</button>
              <button className="btn" onClick={() => navigate("/reports")}><LuHistory />Reports</button>
            </div>
          </Card>
          <Card title="Recent activity" icon={<LuActivity />}><ActivityFeed items={data.recent_activity} /></Card>
        </div>
      </div>
    </>
  );
}
