// Minimal History-API router (no external dependency).
import { createContext, useContext, useEffect, useState, type ReactNode, type MouseEvent } from "react";

type Loc = { path: string; search: URLSearchParams };
const RouterCtx = createContext<Loc>({ path: "/", search: new URLSearchParams() });

function current(): Loc {
  return { path: window.location.pathname, search: new URLSearchParams(window.location.search) };
}

export function navigate(to: string, replace = false) {
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event("resq:navigate"));
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [loc, setLoc] = useState<Loc>(current());
  useEffect(() => {
    const update = () => setLoc(current());
    window.addEventListener("popstate", update);
    window.addEventListener("resq:navigate", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("resq:navigate", update);
    };
  }, []);
  return <RouterCtx.Provider value={loc}>{children}</RouterCtx.Provider>;
}

export function useLocation() {
  return useContext(RouterCtx);
}

export function useQueryParam(name: string): [string | null, (v: string | null) => void] {
  const loc = useLocation();
  const value = loc.search.get(name);
  const set = (v: string | null) => {
    const s = new URLSearchParams(window.location.search);
    if (v === null || v === "") s.delete(name); else s.set(name, v);
    const q = s.toString();
    navigate(window.location.pathname + (q ? `?${q}` : ""), true);
  };
  return [value, set];
}

/** Match "/projects/:pid/impact" against a path; returns params or null. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/").filter(Boolean);
  const a = path.split("/").filter(Boolean);
  if (p.length !== a.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(a[i]);
    else if (p[i] !== a[i]) return null;
  }
  return params;
}

export function Link({ to, children, className, title }: { to: string; children: ReactNode; className?: string; title?: string }) {
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(to);
  };
  return <a href={to} onClick={onClick} className={className} title={title}>{children}</a>;
}
