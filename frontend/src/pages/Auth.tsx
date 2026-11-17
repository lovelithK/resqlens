import { useState, type FormEvent } from "react";
import { LuLogIn, LuUserPlus } from "react-icons/lu";
import { useAuth } from "../lib/auth";
import { useFeedback } from "../lib/feedback";
import { ApiError } from "../lib/api";
import { Link, navigate } from "../lib/router";
import { BrandLogo } from "../components/Layout";
import { Field } from "../components/ui";

function LensHero() {
  // Miniature of the product: a database fails, the failure spreads to its dependents,
  // then the recovery wave restores them (12 s loop; static when reduced motion is on).
  const nodes: [number, number, string][] = [
    [100, 50, ""], [100, 78, ""], [60, 104, ""], [100, 106, "n-d1"], [140, 104, "n-d2"],
    [128, 134, "n-d2"], [100, 152, "n-src"], [62, 140, ""],
  ];
  const edges: [number, number, string][] = [
    [0, 1, ""], [1, 2, ""], [1, 3, ""], [1, 4, ""], [3, 6, "e1"], [5, 3, "e2"], [4, 5, "e2"], [2, 7, ""], [3, 7, ""],
  ];
  const ticks = Array.from({ length: 48 }, (_, i) => i * 7.5);
  return (
    <svg className="auth-lens" viewBox="0 0 200 200" role="img" aria-label="Animated example: a database failure spreads to dependent services and is then recovered">
      <defs>
        <clipPath id="lens-clip"><circle cx="100" cy="100" r="78" /></clipPath>
        <radialGradient id="lens-glass" cx="42%" cy="38%" r="70%">
          <stop offset="0%" stopColor="#1d4250" /><stop offset="70%" stopColor="#14303a" /><stop offset="100%" stopColor="#0f2229" />
        </radialGradient>
      </defs>
      {ticks.map((a) => (
        <line key={a} x1="100" y1={a % 30 === 0 ? 4 : 6} x2="100" y2="11" stroke={a % 30 === 0 ? "#86a2a9" : "#2d5562"} strokeWidth={a % 30 === 0 ? 1.2 : 0.8} transform={`rotate(${a} 100 100)`} />
      ))}
      <circle cx="100" cy="100" r="86" fill="none" stroke="#2d5562" strokeWidth="1" />
      <circle cx="100" cy="100" r="80" fill="url(#lens-glass)" stroke="#e3edef" strokeWidth="2.5" />
      <path d="M31 72 A75 75 0 0 1 100 22" fill="none" stroke="#a69bff" strokeWidth="4" strokeLinecap="round" />
      <g clipPath="url(#lens-clip)">
        {edges.map(([a, b, c], i) => (
          <line key={i} className={`lens-edge ${c}`} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} />
        ))}
        <circle className="lens-ring" cx={nodes[6][0]} cy={nodes[6][1]} r="8" />
        {nodes.map(([x, y, c], i) => <circle key={i} className={`lens-node ${c}`} cx={x} cy={y} r={c === "n-src" ? 7 : 6} />)}
      </g>
    </svg>
  );
}

function Side() {
  return (
    <div className="auth-side">
      <BrandLogo />
      <div>
        <h1>See how a failure spreads before it reaches your users.</h1>
        <p className="lede">Model your system, break one part on purpose, and get a recovery order you can explain to your team.</p>
      </div>
      <LensHero />
      <div className="col" style={{ gap: 14 }}>
        <div className="auth-legend">
          <span><span className="dotline" style={{ background: "var(--healthy)" }} />Healthy</span>
          <span><span className="dotline" style={{ background: "var(--failed)" }} />Failed</span>
          <span><span className="dotline" style={{ background: "var(--blocked)" }} />Blocked by a dependency</span>
          <span><span className="dotline" style={{ background: "var(--recovering)" }} />Recovering</span>
        </div>
        <p className="foot">Every failure in ResQLens is simulated against the architecture you model. Nothing runs on real infrastructure.</p>
      </div>
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
          <div><h1>Sign in</h1><p className="muted mt8">Continue to your projects and simulations.</p></div>
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
          <div><h1>Create your account</h1><p className="muted mt8">Model an architecture and run your first failure simulation in minutes.</p></div>
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
