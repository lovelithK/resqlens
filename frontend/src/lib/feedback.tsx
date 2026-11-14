// Toast notifications and confirmation dialogs.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { LuCircleAlert, LuCircleCheck, LuInfo, LuTriangleAlert, LuX } from "react-icons/lu";
import { ApiError } from "./api";

type Level = "success" | "error" | "warning" | "info";
type Toast = { id: number; level: Level; message: string };
type ConfirmOpts = { title: string; message: ReactNode; confirmLabel?: string; danger?: boolean };

const Ctx = createContext<{
  toast: (level: Level, message: string) => void;
  error: (e: unknown) => void;
  notify: (items?: { level: string; message: string; type?: string }[]) => void;
  confirm: (o: ConfirmOpts) => Promise<boolean>;
}>(null as any);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dialog, setDialog] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null);
  const seq = useRef(1);

  const toast = useCallback((level: Level, message: string) => {
    const id = seq.current++;
    setToasts((t) => [...t.slice(-4), { id, level, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), level === "error" ? 7000 : 4500);
  }, []);
  const error = useCallback((e: unknown) => {
    if (e instanceof ApiError) {
      let msg = e.message;
      if (Array.isArray(e.details) && e.details.length && e.details[0]?.message && e.code !== "VALIDATION_ERROR") {
        msg += ` — ${e.details.slice(0, 2).map((d: any) => d.message).join("; ")}`;
      }
      toast("error", msg);
    } else toast("error", (e as Error)?.message || "Something went wrong");
  }, [toast]);
  const notify = useCallback((items?: { level: string; message: string; type?: string }[]) => {
    // only milestone events become toasts; every event is still in the timeline / activity log
    const milestones = ["PROPAGATION_COMPLETED", "SYSTEM_RECOVERED", "RECOVERY_INCOMPLETE", "RECOVERY_ACTION_FAILED", "SIMULATION_RESET"];
    (items || []).filter((n) => !n.type || milestones.includes(n.type)).slice(-2).forEach((n) => toast((n.level as Level) || "info", n.message));
  }, [toast]);
  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => setDialog({ ...o, resolve })), []);

  const icon = (l: Level) => l === "success" ? <LuCircleCheck color="var(--healthy)" /> : l === "error" ? <LuCircleAlert color="var(--failed)" />
    : l === "warning" ? <LuTriangleAlert color="var(--degraded)" /> : <LuInfo color="var(--accent)" />;

  const close = (v: boolean) => { dialog?.resolve(v); setDialog(null); };
  return (
    <Ctx.Provider value={{ toast, error, notify, confirm }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.level}`}>
            {icon(t.level)}<div style={{ flex: 1 }}>{t.message}</div>
            <button className="btn ghost sm icon" aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}><LuX /></button>
          </div>
        ))}
      </div>
      {dialog && (
        <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && close(false)}>
          <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" style={{ maxWidth: 440 }}>
            <div className="modal-head">{dialog.danger ? <LuTriangleAlert color="var(--failed)" /> : <LuInfo color="var(--accent)" />}<h2 id="confirm-title">{dialog.title}</h2></div>
            <div className="modal-body muted">{dialog.message}</div>
            <div className="modal-foot">
              <button className="btn" onClick={() => close(false)}>Cancel</button>
              <button className={`btn ${dialog.danger ? "danger" : "primary"}`} autoFocus onClick={() => close(true)}>{dialog.confirmLabel || "Confirm"}</button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  );
}

export function useFeedback() {
  return useContext(Ctx);
}
