import { useState } from "react";
import { LuKeyRound, LuLogOut, LuSave, LuUser } from "react-icons/lu";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { fmtDate } from "../lib/format";
import { Card, Field, PageHeader } from "../components/ui";

export default function SettingsPage() {
  const { user, refresh, logout } = useAuth();
  const { toast, error } = useFeedback();
  const catalog = useApi<any>("/catalog");
  const [name, setName] = useState(user?.full_name || "");
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [pwErr, setPwErr] = useState("");

  const saveProfile = async () => {
    try { await api.put("/auth/me", { full_name: name }); await refresh(); toast("success", "Profile updated"); } catch (e) { error(e); }
  };
  const changePw = async () => {
    if (pw.new_password.length < 8) { setPwErr("At least 8 characters"); return; }
    if (pw.new_password !== pw.confirm) { setPwErr("Passwords do not match"); return; }
    setPwErr("");
    try { await api.post("/auth/change-password", { current_password: pw.current_password, new_password: pw.new_password }); setPw({ current_password: "", new_password: "", confirm: "" }); toast("success", "Password changed"); }
    catch (e) { error(e); }
  };
  return (
    <>
      <PageHeader title="Settings" description="Account, security and reference information about the analysis models." />
      <div className="grid g2">
        <Card title="Profile" icon={<LuUser />}>
          <div className="col" style={{ gap: 12 }}>
            <Field label="Full name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Email"><input className="input" value={user?.email || ""} disabled /></Field>
            <span className="faint xs">Member since {fmtDate(user?.created_at, false)}</span>
            <div className="row"><button className="btn primary sm" disabled={name.trim().length < 2} onClick={saveProfile}><LuSave />Save profile</button><div className="spacer" /><button className="btn sm" onClick={logout}><LuLogOut />Sign out</button></div>
          </div>
        </Card>
        <Card title="Change password" icon={<LuKeyRound />}>
          <div className="col" style={{ gap: 12 }}>
            <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label="New password" help="Min. 8 characters with letters and a digit"><input className="input" type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Field label="Confirm new password" error={pwErr}><input className="input" type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
            <button className="btn sm" style={{ alignSelf: "flex-start" }} disabled={!pw.current_password || !pw.new_password} onClick={changePw}>Update password</button>
          </div>
        </Card>
        <Card title="Propagation policies">
          <div className="col small" style={{ gap: 10 }}>{(catalog.data?.propagation_policies || []).map((p: any) => <div key={p.key}><b>{p.name}</b><div className="muted">{p.description}</div></div>)}</div>
        </Card>
        <Card title="Recovery strategies">
          <div className="col small" style={{ gap: 10 }}>{(catalog.data?.recovery_strategies || []).map((s: any) => <div key={s.key}><b>{s.name}</b><div className="muted">{s.description}</div><div className="faint xs">{s.guarantee}</div></div>)}</div>
        </Card>
        <Card title="Failure types">
          <div className="col small" style={{ gap: 8 }}>{(catalog.data?.failure_types || []).map((f: any) => <div key={f.type}><b>{f.label}</b> <span className="muted">– {f.description}</span>{f.applicable_types && <span className="faint xs"> (only {f.applicable_types.join(", ").toLowerCase()})</span>}</div>)}</div>
        </Card>
        <Card title="Operating rules">
          <div className="col small" style={{ gap: 8 }}>{(catalog.data?.operating_rules || []).map((r: any) => <div key={r.value}><b>{r.value}</b> <span className="muted">– {r.description}</span></div>)}</div>
          <p className="faint xs mt12">A lost mandatory dependency always makes a component unavailable, regardless of its rule.</p>
        </Card>
      </div>
    </>
  );
}
