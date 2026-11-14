import "./styles.css";
import { createRoot } from "react-dom/client";
import { useEffect, type ReactNode } from "react";
import { AuthProvider, useAuth } from "./lib/auth";
import { FeedbackProvider } from "./lib/feedback";
import { match, navigate, RouterProvider, useLocation } from "./lib/router";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import { LoginPage, RegisterPage } from "./pages/Auth";
import DashboardPage from "./pages/Dashboard";
import ProjectsPage from "./pages/Projects";
import WorkspacePage from "./pages/Workspace";
import ArchitecturePage from "./pages/Architecture";
import SimulationPage from "./pages/Simulation";
import ImpactPage from "./pages/Impact";
import RootCausePage from "./pages/RootCause";
import RecoveryPlannerPage from "./pages/RecoveryPlanner";
import ExecutionPage from "./pages/Execution";
import ResiliencePage from "./pages/Resilience";
import WhatIfPage from "./pages/WhatIf";
import HistoryPage from "./pages/History";
import ReportsPage from "./pages/Reports";
import SettingsPage from "./pages/Settings";

type R = { path: string; render: (p: Record<string, string>) => ReactNode; flush?: boolean };
const routes: R[] = [
  { path: "/", render: () => <DashboardPage /> },
  { path: "/projects", render: () => <ProjectsPage /> },
  { path: "/projects/:pid", render: (p) => <WorkspacePage pid={+p.pid} /> },
  { path: "/projects/:pid/architecture", render: (p) => <ArchitecturePage pid={+p.pid} />, flush: true },
  { path: "/projects/:pid/simulation", render: (p) => <SimulationPage pid={+p.pid} />, flush: true },
  { path: "/projects/:pid/impact", render: (p) => <ImpactPage pid={+p.pid} /> },
  { path: "/projects/:pid/root-cause", render: (p) => <RootCausePage pid={+p.pid} /> },
  { path: "/projects/:pid/recovery", render: (p) => <RecoveryPlannerPage pid={+p.pid} /> },
  { path: "/projects/:pid/execution", render: (p) => <ExecutionPage pid={+p.pid} />, flush: true },
  { path: "/projects/:pid/resilience", render: (p) => <ResiliencePage pid={+p.pid} /> },
  { path: "/projects/:pid/what-if", render: (p) => <WhatIfPage pid={+p.pid} /> },
  { path: "/history", render: () => <HistoryPage /> },
  { path: "/reports", render: () => <ReportsPage /> },
  { path: "/settings", render: () => <SettingsPage /> },
];

function Routes() {
  const { user, ready } = useAuth();
  const loc = useLocation();
  const publicPage = loc.path === "/login" || loc.path === "/register";
  useEffect(() => {
    if (!ready) return;
    if (!user && !publicPage) navigate("/login", true);
    if (user && publicPage) navigate("/", true);
  }, [ready, user, publicPage]);
  if (!ready) return <Loading label="Starting ResQLens…" />;
  if (!user) return loc.path === "/register" ? <RegisterPage /> : <LoginPage />;
  for (const r of routes) {
    const params = match(r.path, loc.path);
    if (params) return <Layout flush={r.flush}>{r.render(params)}</Layout>;
  }
  return <Layout><div className="empty"><h3>Page not found</h3><a href="/" onClick={(e) => { e.preventDefault(); navigate("/"); }}>Back to dashboard</a></div></Layout>;
}

createRoot(document.getElementById("root")!).render(
  <RouterProvider>
    <FeedbackProvider>
      <AuthProvider>
        <Routes />
      </AuthProvider>
    </FeedbackProvider>
  </RouterProvider>,
);
