import { useEffect, type ReactNode } from "react";
import {
  LuBox, LuCircleAlert, LuCpu, LuDatabase, LuGlobe, LuHardDrive, LuInbox, LuInfo, LuKeyRound, LuLayers, LuMonitor,
  LuRouter, LuServer, LuTriangleAlert, LuX, LuCircleCheck,
} from "react-icons/lu";
import { title } from "../lib/format";

export const TYPE_ICON: Record<string, any> = {
  FRONTEND: LuMonitor, BACKEND: LuServer, API_GATEWAY: LuRouter, AUTH: LuKeyRound, DATABASE: LuDatabase,
  CACHE: LuLayers, MESSAGE_QUEUE: LuInbox, EXTERNAL_API: LuGlobe, STORAGE: LuHardDrive, CUSTOM: LuBox,
};

export function TypeIcon({ type, size = 16, color }: { type: string; size?: number; color?: string }) {
  const I = TYPE_ICON[type] || LuCpu;
  return <I size={size} color={color} />;
}

export function Badge({ value, label, dot }: { value?: string | null; label?: ReactNode; dot?: boolean }) {
  if (!value && !label) return null;
  return <span className={`badge ${value || ""}`}>{dot && <span className="dot" />}{label ?? title(value)}</span>;
}

export function Card({ title: t, sub, actions, children, className = "", bodyClass = "card-body", icon }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children?: ReactNode; className?: string; bodyClass?: string; icon?: ReactNode;
}) {
  return (
    <section className={`card ${className}`}>
      {(t || actions) && (
        <div className="card-head">
          {icon}
          <div style={{ minWidth: 0 }}><h2>{t}</h2>{sub && <div className="sub">{sub}</div>}</div>
          <div className="spacer" />{actions}
        </div>
      )}
      {children !== undefined && <div className={bodyClass}>{children}</div>}
    </section>
  );
}

export function Stat({ label, value, hint, icon, color }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; color?: string }) {
  return (
    <div className="card stat">
      <div className="label">{icon}{label}</div>
      <div className="value" style={color ? { color } : undefined}>{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function PageHeader({ title: t, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{t}</h1>{description && <p>{description}</p>}</div>
      {actions && <div className="row wrap">{actions}</div>}
    </div>
  );
}

export function Empty({ icon, title: t, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty">{icon || <LuInbox />}<h3>{t}</h3>{children && <div style={{ maxWidth: 440 }}>{children}</div>}{action}</div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading-block"><div className="spinner" />{label}</div>;
}

export function Callout({ kind = "info", children }: { kind?: "info" | "warn" | "error" | "success"; children: ReactNode }) {
  const I = kind === "error" ? LuCircleAlert : kind === "warn" ? LuTriangleAlert : kind === "success" ? LuCircleCheck : LuInfo;
  return <div className={`callout ${kind}`}><I />{<div style={{ flex: 1 }}>{children}</div>}</div>;
}

export function Modal({ title: t, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">
        <div className="modal-head"><h2>{t}</h2><div className="spacer" /><button className="btn ghost icon sm" aria-label="Close" onClick={onClose}><LuX /></button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, help, error, children, className = "", htmlFor }: { label: string; help?: ReactNode; error?: string; children: ReactNode; className?: string; htmlFor?: string }) {
  return (
    <div className={`field ${className}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? <div className="err">{error}</div> : help && <div className="help">{help}</div>}
    </div>
  );
}

export function Progress({ value, color }: { value: number; color?: string }) {
  return <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
    <div style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
  </div>;
}

export function HealthBar({ value }: { value: number }) {
  const c = value >= 85 ? "var(--healthy)" : value >= 50 ? "var(--degraded)" : "var(--failed)";
  return <div className="bar-inline"><Progress value={value / 100} color={c} /><span className="num small" style={{ width: 42, textAlign: "right" }}>{Math.round(value)}%</span></div>;
}

export function PathView({ names }: { names: string[] }) {
  return <div className="path">{names.map((n, i) => <span key={i} className="row" style={{ gap: 5 }}>{i > 0 && <span className="arrow">→</span>}<span className="chip">{n}</span></span>)}</div>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return <div className="tabs" role="tablist">{tabs.map((t) => (
    <button key={t.key} role="tab" aria-selected={value === t.key} className={`tab ${value === t.key ? "active" : ""}`} onClick={() => onChange(t.key)}>{t.label}</button>
  ))}</div>;
}
