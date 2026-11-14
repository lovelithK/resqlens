import { useEffect, useState, type ReactNode } from "react";
import {
  LuActivity, LuChevronsLeft, LuChevronsRight, LuFileText, LuFlaskConical, LuFolderKanban, LuGauge, LuGitCompare,
  LuHistory, LuLayoutDashboard, LuLogOut, LuNetwork, LuPlay, LuSearch, LuSettings, LuShieldCheck, LuWrench, LuZap,
} from "react-icons/lu";
import { useAuth } from "../lib/auth";
import { Link, navigate, useLocation } from "../lib/router";
import { api } from "../lib/api";

const LAST_PROJECT = "resqlens.lastProject";

export function rememberProject(id: number | string) {
  try { localStorage.setItem(LAST_PROJECT, String(id)); } catch { /* ignore */ }
}
export function lastProject(): string | null {
  try { return localStorage.getItem(LAST_PROJECT); } catch { return null; }
}

function Logo() {
  return (
    <div className="brand-mark" aria-hidden>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <circle cx="10.5" cy="10.5" r="6.5" stroke="#22d3ee" strokeWidth="2.2" />
        <path d="M15.5 15.5L21 21" stroke="#3b82f6" strokeWidth="2.4" strokeLinecap="round" />
        <path d="M7.5 10.5h2l1-2 1.5 4 1-2h1.5" stroke="#e5ecf6" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export function BrandLogo() {
  return <div className="row" style={{ gap: 10 }}><Logo /><span className="brand-name">ResQ<span>Lens</span></span></div>;
}

export default function Layout({ children, flush }: { children: ReactNode; flush?: boolean }) {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("resqlens.sidebar") === "1"; } catch { return false; }
  });
  const [projects, setProjects] = useState<{ id: number; name: string }[]>([]);
  const m = loc.path.match(/^\/projects\/(\d+)/);
  const pid = m ? m[1] : lastProject();

  useEffect(() => { if (m) rememberProject(m[1]); }, [m?.[1]]);
  useEffect(() => { api.get("/projects").then(setProjects).catch(() => setProjects([])); }, [loc.path]);
  useEffect(() => { try { localStorage.setItem("resqlens.sidebar", collapsed ? "1" : "0"); } catch { /* ignore */ } }, [collapsed]);

  const validPid = pid && projects.some((p) => String(p.id) === pid) ? pid : projects[0] ? String(projects[0].id) : null;
  const project = projects.find((p) => String(p.id) === validPid);
  const item = (to: string, icon: ReactNode, label: string, exact = false, disabled = false) => {
    const active = exact ? loc.path === to : loc.path === to || loc.path.startsWith(to + "/");
    return (
      <Link key={to} to={to} className={`nav-item ${active ? "active" : ""} ${disabled ? "disabled" : ""}`} title={collapsed ? label : undefined}>
        {icon}<span className="nav-label">{label}</span>
      </Link>
    );
  };
  const P = (suffix: string) => `/projects/${validPid}${suffix}`;
  const projectActive = (suffix: string) => loc.path === P(suffix);
  const pItem = (suffix: string, icon: ReactNode, label: string) => (
    <Link key={suffix} to={P(suffix) + (suffix && suffix !== "/architecture" && loc.search.get("sim") ? `?sim=${loc.search.get("sim")}` : "")}
      className={`nav-item ${projectActive(suffix) ? "active" : ""}`} title={collapsed ? label : undefined}>
      {icon}<span className="nav-label">{label}</span>
    </Link>
  );

  const crumbs = (() => {
    const map: Record<string, string> = {
      "": "Workspace", architecture: "Architecture Builder", simulation: "Failure Simulation", impact: "Impact Analysis",
      "root-cause": "Root Cause Analysis", recovery: "Recovery Planner", execution: "Recovery Execution",
      resilience: "Resilience Analytics", "what-if": "What-If Comparison",
    };
    if (m) {
      const rest = loc.path.split("/")[3] || "";
      return <><Link to="/projects">Projects</Link><span>/</span><span className="ellipsis" style={{ maxWidth: 280 }}>{project?.name || "Project"}</span><span>/</span><strong>{map[rest] || rest}</strong></>;
    }
    const top: Record<string, string> = { "/": "Dashboard", "/projects": "Projects", "/history": "Simulation History", "/reports": "Reports", "/settings": "Settings" };
    return <strong>{top[loc.path] || ""}</strong>;
  })();

  return (
    <div className="app">
      <aside className={`sidebar ${collapsed ? "collapsed" : ""}`} aria-label="Main navigation">
        <div className="brand"><Logo /><span className="brand-name">ResQ<span>Lens</span></span></div>
        <nav className="nav">
          {item("/", <LuLayoutDashboard />, "Dashboard", true)}
          {item("/projects", <LuFolderKanban />, "Projects", true)}
          <div className="nav-section">{project ? project.name : "Project"}</div>
          {validPid ? <>
            {pItem("", <LuActivity />, "Workspace")}
            {pItem("/architecture", <LuNetwork />, "Architecture Builder")}
            {pItem("/simulation", <LuZap />, "Failure Simulation")}
            {pItem("/impact", <LuGauge />, "Impact Analysis")}
            {pItem("/root-cause", <LuSearch />, "Root Cause Analysis")}
            {pItem("/recovery", <LuWrench />, "Recovery Planner")}
            {pItem("/execution", <LuPlay />, "Recovery Execution")}
            {pItem("/resilience", <LuShieldCheck />, "Resilience Analytics")}
            {pItem("/what-if", <LuGitCompare />, "What-If Scenarios")}
          </> : <div className="nav-item disabled"><LuFlaskConical /><span className="nav-label">Create a project first</span></div>}
          <div className="nav-section">Records</div>
          {item("/history", <LuHistory />, "Simulation History", true)}
          {item("/reports", <LuFileText />, "Reports", true)}
          {item("/settings", <LuSettings />, "Settings", true)}
        </nav>
        <div className="sidebar-foot">
          <button className="nav-item w100" style={{ background: "none", font: "inherit" }} onClick={() => setCollapsed(!collapsed)} aria-label="Toggle sidebar">
            {collapsed ? <LuChevronsRight /> : <LuChevronsLeft />}<span className="nav-label sidebar-foot-text">Collapse</span>
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="crumbs">{crumbs}</div>
          <div className="spacer" />
          {projects.length > 0 && (
            <select className="select sm" style={{ width: 240 }} aria-label="Switch project" value={validPid || ""}
              onChange={(e) => { rememberProject(e.target.value); navigate(m ? loc.path.replace(/^\/projects\/\d+/, `/projects/${e.target.value}`) : `/projects/${e.target.value}`); }}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          <div className="row small" style={{ gap: 8 }}>
            <div style={{ width: 30, height: 30, borderRadius: 8, background: "var(--panel-3)", display: "grid", placeItems: "center", fontWeight: 600 }} aria-hidden>
              {(user?.full_name || "?").split(" ").map((s) => s[0]).slice(0, 2).join("")}
            </div>
            <div className="col" style={{ gap: 0 }}><span className="strong">{user?.full_name}</span><span className="faint xs">{user?.email}</span></div>
          </div>
          <button className="btn ghost sm icon" title="Sign out" aria-label="Sign out" onClick={logout}><LuLogOut /></button>
        </header>
        <main className={`content ${flush ? "flush" : ""}`}>{children}</main>
      </div>
    </div>
  );
}
