import { useState, type FormEvent } from "react";
import { LuLogIn, LuUserPlus } from "react-icons/lu";
import { useAuth } from "../lib/auth";
import { useFeedback } from "../lib/feedback";
import { ApiError } from "../lib/api";
import { Link, navigate } from "../lib/router";
import { BrandLogo } from "../components/Layout";
import { Field } from "../components/ui";

function Side() {
  const qs = [
    ["01", "Which component failed?"], ["02", "Why did the failure affect other components?"],
    ["03", "Which services and functionalities are affected?"], ["04", "What should be recovered first?"],
    ["05", "How can the system become more resilient?"],
  ];
  return (
    <div className="auth-side">
      <BrandLogo />
      <h1>Diagnose cascading failures and plan recovery with a deterministic, explainable engine.</h1>
      <div className="col" style={{ gap: 14 }}>
        {qs.map(([n, q]) => <div key={n} className="q"><b>{n}</b><span>{q}</span></div>)}
      </div>
      <p className="faint small" style={{ maxWidth: 500 }}>
        All failures in ResQLens are simulated against your modelled architecture. No command is ever executed on real infrastructure.
      </p>
    </div>
  );
}

export function LoginPage() {
  const { login } = useAuth();
  const { error } = useFeedback();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await login(email, password);
      navigate("/", true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setMsg(err.message); else error(err);
    } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Side />
      <div className="auth-form">
        <form className="auth-card col" style={{ gap: 16 }} onSubmit={submit} noValidate>
          <div><h1>Sign in</h1><p className="muted mt8">Welcome back. Continue to your resilience workspace.</p></div>
          {msg && <div className="callout error" role="alert">{msg}</div>}
          <Field label="Email" htmlFor="email"><input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password" htmlFor="password"><input id="password" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <button className="btn primary" disabled={busy || !email || !password}>{busy ? <span className="spinner" /> : <LuLogIn />}Sign in</button>
          <p className="muted small">No account yet? <Link to="/register">Create one</Link></p>
        </form>
      </div>
    </div>
  );
}

export function RegisterPage() {
  const { register } = useAuth();
  const { error, toast } = useFeedback();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", confirm: "", include_demo_project: true });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));
  const validate = () => {
    const e: Record<string, string> = {};
    if (form.full_name.trim().length < 2) e.full_name = "Enter your name";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email)) e.email = "Enter a valid email address";
    if (form.password.length < 8) e.password = "At least 8 characters";
    else if (!/\d/.test(form.password) || !/[a-z]/i.test(form.password)) e.password = "Use letters and at least one digit";
    if (form.confirm !== form.password) e.confirm = "Passwords do not match";
    setErrors(e);
    return !Object.keys(e).length;
  };
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      const { confirm: _c, ...data } = form;
      await register(data);
      toast("success", form.include_demo_project ? "Account created with the demo architecture" : "Account created");
      navigate("/", true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "EMAIL_TAKEN") setErrors({ email: err.message }); else error(err);
    } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Side />
      <div className="auth-form">
        <form className="auth-card col" style={{ gap: 14 }} onSubmit={submit} noValidate>
          <div><h1>Create account</h1><p className="muted mt8">Start modelling and stress-testing your architectures.</p></div>
          <Field label="Full name" htmlFor="name" error={errors.full_name}><input id="name" className="input" autoComplete="name" value={form.full_name} onChange={(e) => set("full_name", e.target.value)} /></Field>
          <Field label="Email" htmlFor="remail" error={errors.email}><input id="remail" className="input" type="email" autoComplete="email" value={form.email} onChange={(e) => set("email", e.target.value)} /></Field>
          <Field label="Password" htmlFor="rpw" error={errors.password} help="Min. 8 characters with letters and a digit"><input id="rpw" className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => set("password", e.target.value)} /></Field>
          <Field label="Confirm password" htmlFor="rpw2" error={errors.confirm}><input id="rpw2" className="input" type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => set("confirm", e.target.value)} /></Field>
          <label className="check"><input type="checkbox" checked={form.include_demo_project} onChange={(e) => set("include_demo_project", e.target.checked)} />Add the “University Examination Management System” demo project</label>
          <button className="btn primary" disabled={busy}>{busy ? <span className="spinner" /> : <LuUserPlus />}Create account</button>
          <p className="muted small">Already registered? <Link to="/login">Sign in</Link></p>
        </form>
      </div>
    </div>
  );
}
