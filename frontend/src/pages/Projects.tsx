import { useEffect, useRef, useState } from "react";
import { LuFolderPlus, LuNetwork, LuTrash2, LuUpload, LuZap, LuFolderOpen } from "react-icons/lu";
import { api } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { navigate, useQueryParam } from "../lib/router";
import { ago } from "../lib/format";
import { Card, Empty, Field, HealthBar, Loading, Modal, PageHeader, Badge } from "../components/ui";

export function ProjectForm({ initial, onSubmit, onClose, title }: { initial?: any; onSubmit: (d: any) => Promise<void>; onClose: () => void; title: string }) {
  const [form, setForm] = useState({ name: initial?.name || "", description: initial?.description || "", propagation_policy: initial?.propagation_policy || "BLOCKING" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async () => {
    if (form.name.trim().length < 2) { setErr("Name must be at least 2 characters"); return; }
    setBusy(true);
    try { await onSubmit(form); } finally { setBusy(false); }
  };
  return (
    <Modal title={title} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy} onClick={submit}>{busy && <span className="spinner" />}Save</button></>}>
      <div className="col" style={{ gap: 14 }}>
        <Field label="Project name" error={err}><input className="input" autoFocus value={form.name} onChange={(e) => { setForm({ ...form, name: e.target.value }); setErr(""); }} /></Field>
        <Field label="Description"><textarea className="textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label="Dependency failure policy" help="How a component behaves when a mandatory dependency becomes unavailable.">
          <select className="select" value={form.propagation_policy} onChange={(e) => setForm({ ...form, propagation_policy: e.target.value })}>
            <option value="BLOCKING">Blocking – dependent becomes BLOCKED (process intact, cannot serve)</option>
            <option value="FAIL_FAST">Fail-fast – dependent becomes FAILED (needs a restart)</option>
          </select>
        </Field>
      </div>
    </Modal>
  );
}

export default function ProjectsPage() {
  const { data, loading, reload } = useApi<any[]>("/projects");
  const { toast, error, confirm } = useFeedback();
  const [newParam, setNewParam] = useQueryParam("new");
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (newParam) { setCreating(true); setNewParam(null); } }, [newParam]);

  const create = async (form: any) => {
    try {
      const p = await api.post("/projects", form);
      toast("success", `Project '${p.name}' created`);
      navigate(`/projects/${p.id}/architecture`);
    } catch (e) { error(e); }
  };
  const remove = async (p: any) => {
    if (!await confirm({ title: "Delete project?", danger: true, confirmLabel: "Delete project", message: <>This permanently deletes <b>{p.name}</b>, its architecture, simulations and reports.</> })) return;
    try { await api.del(`/projects/${p.id}`); toast("success", "Project deleted"); reload(); } catch (e) { error(e); }
  };
  const importFile = async (f: File) => {
    try {
      const data = JSON.parse(await f.text());
      if (data.format !== "resqlens-architecture/1") throw new Error("Not a ResQLens architecture export file");
      const p = await api.post("/projects/import", { data });
      toast("success", `Imported '${p.name}'`);
      navigate(`/projects/${p.id}/architecture`);
    } catch (e) { error(e); }
  };

  return (
    <>
      <PageHeader title="Projects" description="Each project holds one system architecture, its functionalities, failure scenarios and simulation history."
        actions={<>
          <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
          <button className="btn" onClick={() => fileRef.current?.click()}><LuUpload />Import architecture</button>
          <button className="btn primary" onClick={() => setCreating(true)}><LuFolderPlus />New project</button>
        </>} />
      {loading && !data ? <Loading /> : !data?.length ? (
        <Card><Empty icon={<LuFolderOpen />} title="No projects yet" action={<button className="btn primary" onClick={() => setCreating(true)}><LuFolderPlus />Create your first project</button>}>
          Create a project, then add components and dependencies in the Architecture Builder.
        </Empty></Card>
      ) : (
        <div className="grid g3">
          {data.map((p) => (
            <div key={p.id} className="card hoverable" style={{ cursor: "pointer" }} onClick={() => navigate(`/projects/${p.id}`)}>
              <div className="card-body col" style={{ gap: 12 }}>
                <div className="row"><h2 className="ellipsis">{p.name}</h2><div className="spacer" />{p.failed_count > 0 && <Badge value="FAILED" label={`${p.failed_count} down`} dot />}</div>
                <p className="muted small" style={{ minHeight: 38 }}>{p.description || "No description"}</p>
                <div className="grid g3 small">
                  <div><div className="faint xs">Components</div><div className="strong num">{p.component_count}</div></div>
                  <div><div className="faint xs">Dependencies</div><div className="strong num">{p.dependency_count}</div></div>
                  <div><div className="faint xs">Simulations</div><div className="strong num">{p.simulation_count}</div></div>
                </div>
                <div><div className="faint xs" style={{ marginBottom: 4 }}>Live health</div><HealthBar value={p.current_health} /></div>
                <div className="row" onClick={(e) => e.stopPropagation()}>
                  <span className="faint xs">Policy: {p.propagation_policy.replace("_", "-").toLowerCase()} · {ago(p.last_activity_at || p.created_at)}</span>
                  <div className="spacer" />
                  <button className="btn sm icon" title="Architecture" aria-label="Open architecture" onClick={() => navigate(`/projects/${p.id}/architecture`)}><LuNetwork /></button>
                  <button className="btn sm icon" title="Simulate" aria-label="Simulate" onClick={() => navigate(`/projects/${p.id}/simulation`)}><LuZap /></button>
                  <button className="btn sm icon danger" title="Delete" aria-label="Delete project" onClick={() => remove(p)}><LuTrash2 /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {creating && <ProjectForm title="New project" onClose={() => setCreating(false)} onSubmit={create} />}
    </>
  );
}
