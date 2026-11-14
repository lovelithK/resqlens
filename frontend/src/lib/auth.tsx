import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { navigate } from "./router";

export type User = { id: number; email: string; full_name: string; created_at: string };

const AuthCtx = createContext<{
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { email: string; full_name: string; password: string; include_demo_project: boolean }) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}>(null as any);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const clear = useCallback(() => {
    setToken(null);
    setUser(null);
    if (!["/login", "/register"].includes(window.location.pathname)) navigate("/login");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(clear);
    if (!getToken()) { setReady(true); return; }
    api.get<User>("/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setReady(true));
  }, [clear]);

  const login = async (email: string, password: string) => {
    const r = await api.post("/auth/login", { email, password });
    setToken(r.token);
    setUser(r.user);
  };
  const register = async (data: any) => {
    const r = await api.post("/auth/register", data);
    setToken(r.token);
    setUser(r.user);
  };
  const logout = async () => {
    try { await api.post("/auth/logout"); } catch { /* already invalid */ }
    clear();
  };
  const refresh = async () => setUser(await api.get<User>("/auth/me"));
  return <AuthCtx.Provider value={{ user, ready, login, register, logout, refresh }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
