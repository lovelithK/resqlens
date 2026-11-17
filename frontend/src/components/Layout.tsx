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

export function Logo({ size = 30 }: { size?: number }) {
  // A lens ring with a violet coating arc; inside, a three-node dependency path.
  return (
    <div className="brand-mark" aria-hidden style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
        <circle cx="16" cy="16" r="13" stroke="#e3edef" strokeWidth="2" />
        <path d="M5.2 11.2A12 12 0 0 1 16 3.5" stroke="#a69bff" strokeWidth="2.6" strokeLinecap="round" />
        <path d="M10.5 19.5 16 12.5l5.5 7" stroke="#86a2a9" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="16" cy="12.5" r="2.4" fill="#ff6b66" />
        <circle cx="10.5" cy="19.5" r="2.1" fill="#3fd49a" />
        <circle cx="21.5" cy="19.5" r="2.1" fill="#3fd49a" />
      </svg>
    </div>
  );
}

export function BrandLogo() {
  return <div className="row" style={{ gap: 11 }}><Logo size={34} /><span className="brand-name" style={{ fontSize: 21 }}>ResQ<span>Lens</span></span></div>;
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
            <div className="avatar" aria-hidden>
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
