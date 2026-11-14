import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Load data from the API; returns { data, error, loading, reload, setData }. */
export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);
  const load = useCallback(async (silent = false) => {
    if (!path) { setLoading(false); return; }
    const id = ++seq.current;
    if (!silent) setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (id === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (id === seq.current) setError(e as Error);
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: (silent = true) => load(silent), setData };
}

/** Run a callback on an interval while ``active`` is true. */
export function useInterval(cb: () => void, ms: number, active: boolean) {
  const ref = useRef(cb);
  ref.current = cb;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => ref.current(), ms);
    return () => clearInterval(t);
  }, [ms, active]);
}
