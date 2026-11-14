import { useEffect, useMemo, useRef, useState } from "react";
import {
  LuCheck, LuDownload, LuLink, LuLock, LuPlus, LuSave, LuShieldCheck, LuTrash2, LuUndo2, LuUnlink,
} from "react-icons/lu";
import { api, download } from "../lib/api";
import { useFeedback } from "../lib/feedback";
import { useApi } from "../lib/hooks";
import { navigate, useQueryParam } from "../lib/router";
import { ago, TYPE_LABEL } from "../lib/format";
import GraphCanvas from "../components/GraphCanvas";
import { Badge, Callout, Field, Loading, Modal, Tabs, TypeIcon } from "../components/ui";

const TYPES = Object.keys(TYPE_LABEL);
const CRIT = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const RULES: Record<string, string> = {
  STANDARD: "Standard – degraded mandatory dependency degrades it; optional loss tolerated",
  STRICT: "Strict – also degrades when an optional dependency is lost/degraded",
  TOLERANT: "Tolerant – ignores degraded and optional dependencies",
};
const emptyComponent = {
  name: "", component_type: "BACKEND", description: "", criticality: "MEDIUM", recovery_priority: 3,
  estimated_recovery_minutes: 10, recovery_cost: 10, operating_rule: "STANDARD", baseline_status: "HEALTHY", baseline_health: 100,
};

function ComponentForm({ value, onChange, disabled }: { value: any; onChange: (v: any) => void; disabled?: boolean }) {
  const set = (k: string, v: any) => onChange({ ...value, [k]: v });
  return (
    <div className="form-grid">
      <Field label="Name" className="full"><input className="input" disabled={disabled} value={value.name} onChange={(e) => set("name", e.target.value)} /></Field>
      <Field label="Type"><select className="select" disabled={disabled} value={value.component_type} onChange={(e) => set("component_type", e.target.value)}>{TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select></Field>
      <Field label="Criticality"><select className="select" disabled={disabled} value={value.criticality} onChange={(e) => set("criticality", e.target.value)}>{CRIT.map((c) => <option key={c}>{c}</option>)}</select></Field>
      <Field label="Recovery time (min)" help="Configured estimate"><input className="input" type="number" min={0.5} step={0.5} disabled={disabled} value={value.estimated_recovery_minutes} onChange={(e) => set("estimated_recovery_minutes", +e.target.value)} /></Field>
      <Field label="Recovery cost" help="Relative units"><input className="input" type="number" min={0} disabled={disabled} value={value.recovery_cost} onChange={(e) => set("recovery_cost", +e.target.value)} /></Field>
      <Field label="Recovery priority" help="1 = highest"><select className="select" disabled={disabled} value={value.recovery_priority} onChange={(e) => set("recovery_priority", +e.target.value)}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select></Field>
      <Field label="Baseline status"><select className="select" disabled={disabled} value={value.baseline_status} onChange={(e) => set("baseline_status", e.target.value)}><option>HEALTHY</option><option>DEGRADED</option></select></Field>
      <Field label="Operating rule" className="full"><select className="select" disabled={disabled} value={value.operating_rule} onChange={(e) => set("operating_rule", e.target.value)}>{Object.entries(RULES).map(([k, d]) => <option key={k} value={k}>{d}</option>)}</select></Field>
      <Field label={`Baseline health: ${value.baseline_health}%`} className="full"><input type="range" min={0} max={100} disabled={disabled} value={value.baseline_health} onChange={(e) => set("baseline_health", +e.target.value)} /></Field>
      <Field label="Description" className="full"><textarea className="textarea" disabled={disabled} value={value.description} onChange={(e) => set("description", e.target.value)} /></Field>
    </div>
  );
}

export default function ArchitecturePage({ pid }: { pid: number }) {
  const { data, loading, error: loadError, reload } = useApi<any>(`/projects/${pid}/architecture`, [pid]);
  const history = useApi<any[]>(`/projects/${pid}/commands`, [pid]);
  const { toast, error, confirm } = useFeedback();
  const [selectParam] = useQueryParam("select");
  const [selected, setSelected] = useState<number | null>(selectParam ? +selectParam : null);
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null);
  const [tab, setTab] = useState<"details" | "functionalities" | "validation" | "history">("details");
  const [adding, setAdding] = useState(false);
  const [newComp, setNewComp] = useState<any>(emptyComponent);
  const [draft, setDraft] = useState<any>(null);
  const [connect, setConnect] = useState<{ source: number; target: number; dependency_type: string; fallback_id: string } | null>(null);
  const layoutTimer = useRef<any>(null);
  const pendingPos = useRef<Record<number, { x: number; y: number }>>({});

  const comps: any[] = data?.components || [];
  const deps: any[] = data?.dependencies || [];
  const byId = useMemo(() => Object.fromEntries(comps.map((c) => [c.id, c])), [comps]);
  const locked = !!data?.active_simulation;
  const sel = selected ? byId[selected] : null;
  const edge = selectedEdge ? deps.find((d) => d.id === selectedEdge) : null;

  useEffect(() => {
    if (sel) setDraft({ ...emptyComponent, ...Object.fromEntries(Object.keys(emptyComponent).map((k) => [k, sel[k]])) });
    else setDraft(null);
  }, [selected, data]);

  const refresh = () => { reload(); history.reload(); };
  const run = async (fn: () => Promise<any>, ok?: string) => {
    try { const r = await fn(); if (ok) toast("success", ok); refresh(); return r; } catch (e) { error(e); return null; }
  };

  const savePositions = (pos: Record<number, { x: number; y: number }>) => {
    Object.assign(pendingPos.current, pos);
    clearTimeout(layoutTimer.current);
    layoutTimer.current = setTimeout(() => {
      const positions = Object.entries(pendingPos.current).map(([id, p]) => ({ id: +id, x: p.x, y: p.y }));
      pendingPos.current = {};
      api.put(`/projects/${pid}/layout`, { positions }).catch(() => undefined);
    }, 500);
  };

  if (loading && !data) return <Loading />;
  if (loadError || !data) return <div className="content"><Callout kind="error">{loadError?.message || "Not found"}</Callout></div>;

  const addComponent = async () => {
    if (!newComp.name.trim()) { toast("warning", "Enter a component name"); return; }
    const c = await run(() => api.post(`/projects/${pid}/components`, newComp), `Component '${newComp.name}' added`);
    if (c) { setAdding(false); setNewComp(emptyComponent); setSelected(c.id); setTab("details"); }
  };
  const saveComponent = async () => {
    const changes: any = {};
    Object.keys(emptyComponent).forEach((k) => { if (draft[k] !== sel[k]) changes[k] = draft[k]; });
    if (!Object.keys(changes).length) { toast("info", "No changes to save"); return; }
    await run(() => api.put(`/components/${sel.id}`, changes), "Component saved");
  };
  const deleteComponent = async () => {
    const n = deps.filter((d) => d.source_component_id === sel.id || d.target_component_id === sel.id).length;
    if (!await confirm({ title: `Delete ${sel.name}?`, danger: true, confirmLabel: "Delete", message: `This also removes ${n} connected dependenc${n === 1 ? "y" : "ies"}. You can undo this action.` })) return;
    await run(() => api.del(`/components/${sel.id}`), "Component deleted");
    setSelected(null);
  };
  const createDependency = async () => {
    if (!connect) return;
    const r = await run(() => api.post("/dependencies", {
      project_id: pid, source_id: connect.source, target_id: connect.target, dependency_type: connect.dependency_type,
      fallback_id: connect.fallback_id ? +connect.fallback_id : null,
    }), `${byId[connect.source].name} now depends on ${byId[connect.target].name}`);
    if (r) { setConnect(null); setSelectedEdge(r.id); setSelected(null); }
  };
  const updateDependency = (id: number, changes: any) => run(() => api.put(`/dependencies/${id}`, changes), "Dependency updated");
  const removeDependency = async (id: number) => {
    await run(() => api.del(`/dependencies/${id}`), "Dependency removed");
    setSelectedEdge(null);
  };
  const undo = () => run(async () => { const r = await api.post(`/projects/${pid}/undo`); toast("info", r.description ? `Undone: ${r.description}` : "Undone"); });
  const validate = async () => {
    try {
      const v = await api.post(`/projects/${pid}/validate`);
      setTab("validation");
      reload();
      toast(v.valid ? "success" : "warning", v.valid ? "Architecture is valid – no cycles or broken dependencies" : `${v.error_count} validation error(s) found`);
    } catch (e) { error(e); }
  };

  const DepRow = ({ d, outgoing }: { d: any; outgoing: boolean }) => {
    const other = byId[outgoing ? d.target_component_id : d.source_component_id];
    return (
      <div className="list-item" style={{ padding: "8px 0" }}>
        <div className="row small">
          <TypeIcon type={other?.component_type} size={14} />
          <a href="#" onClick={(e) => { e.preventDefault(); setSelected(other.id); setSelectedEdge(null); }} className="strong">{other?.name}</a>
          <Badge value={d.dependency_type} />
          <div className="spacer" />
          {outgoing && !locked && <button className="btn ghost sm icon" title="Remove dependency" aria-label="Remove dependency" onClick={() => removeDependency(d.id)}><LuUnlink /></button>}
        </div>
        {outgoing && d.fallback_component_id && <div className="xs" style={{ color: "var(--cyan)", marginTop: 3 }}>Backup: {byId[d.fallback_component_id]?.name}</div>}
      </div>
    );
  };

  const v = data.validation;
  return (
    <div className="split">
      <div className="center">
        <div className="toolbar">
          <button className="btn primary sm" disabled={locked} onClick={() => setAdding(true)}><LuPlus />Add component</button>
          <button className="btn sm" disabled={locked || !data.can_undo} onClick={undo} title="Undo last architecture change (Command pattern)"><LuUndo2 />Undo</button>
          <button className="btn sm" onClick={validate}><LuShieldCheck />Validate</button>
          <button className="btn sm" onClick={() => download(`/projects/${pid}/export`, `architecture-${pid}.json`).catch(error)}><LuDownload />Export</button>
          <div className="spacer" />
          {v.valid ? <Badge value="HEALTHY" label="valid architecture" dot /> : <Badge value="FAILED" label={`${v.error_count} error(s)`} dot />}
          <span className="faint xs">{comps.length} components · {deps.length} dependencies · saved automatically</span>
        </div>
        {locked && <div className="banner" style={{ margin: 12, marginBottom: 0 }}><LuLock /><span>Editing is locked while simulation <b>{data.active_simulation.name}</b> is {data.active_simulation.status.toLowerCase()}.</span><div className="spacer" /><button className="btn sm" onClick={() => navigate(`/projects/${pid}/simulation?sim=${data.active_simulation.id}`)}>Go to simulation</button></div>}
        {comps.length === 0 ? (
          <div className="empty" style={{ flex: 1 }}><h3>Start your architecture</h3><p>Add components such as frontends, gateways, services and databases, then drag from a component's bottom handle onto another to declare that it depends on it.</p>
            <button className="btn primary" onClick={() => setAdding(true)}><LuPlus />Add first component</button></div>
        ) : (
          <GraphCanvas nodes={comps} edges={deps} editable={!locked} selectedId={selected} selectedEdgeId={selectedEdge}
            onSelectNode={(id) => { setSelected(id); if (id) { setSelectedEdge(null); setTab("details"); } }}
            onSelectEdge={(id) => { setSelectedEdge(id); if (id) setTab("details"); }}
            onConnect={(s, t) => setConnect({ source: s, target: t, dependency_type: "MANDATORY", fallback_id: "" })}
            onPositionsChange={savePositions}
            hint={!locked ? "Drag nodes to move them · drag a node's bottom handle onto another node to add a dependency" : undefined} />
        )}
      </div>

      <aside className="side" aria-label="Details panel">
        <Tabs value={tab} onChange={setTab} tabs={[{ key: "details", label: "Details" }, { key: "functionalities", label: "Functionalities" },
          { key: "validation", label: <>Validation{!v.valid && <span className="sev-CRITICAL"> ●</span>}</> }, { key: "history", label: "History" }]} />

        {tab === "details" && sel && draft && (
          <>
            <div className="side-section">
              <div className="row"><TypeIcon type={sel.component_type} /><h2 className="ellipsis">{sel.name}</h2><div className="spacer" /><Badge value={sel.status} dot /></div>
              <div className="faint xs mt8">#{sel.id} · {sel.type_label} · created {ago(sel.created_at)} · health {Math.round(sel.health)}%</div>
              {sel.functionalities.length > 0 && <div className="chips mt8">{sel.functionalities.map((f: string) => <span key={f} className="chip">{f}</span>)}</div>}
            </div>
            <div className="side-section"><ComponentForm value={draft} onChange={setDraft} disabled={locked} />
              <div className="row mt12"><button className="btn primary sm" disabled={locked} onClick={saveComponent}><LuSave />Save changes</button><div className="spacer" />
                <button className="btn danger sm" disabled={locked} onClick={deleteComponent}><LuTrash2 />Delete</button></div>
            </div>
            <div className="side-section">
              <div className="section-title">Depends on ({deps.filter((d) => d.source_component_id === sel.id).length})</div>
              {deps.filter((d) => d.source_component_id === sel.id).map((d) => <DepRow key={d.id} d={d} outgoing />)}
              {!locked && <AddDependency sel={sel} comps={comps} deps={deps} onAdd={(target, type) => setConnect({ source: sel.id, target, dependency_type: type, fallback_id: "" })} />}
            </div>
            <div className="side-section">
              <div className="section-title">Used by ({deps.filter((d) => d.target_component_id === sel.id).length})</div>
              {deps.filter((d) => d.target_component_id === sel.id).map((d) => <DepRow key={d.id} d={d} outgoing={false} />)}
              {!deps.some((d) => d.target_component_id === sel.id) && <span className="faint small">No component depends on this one.</span>}
            </div>
          </>
        )}

        {tab === "details" && edge && !sel && (
          <div className="side-section col" style={{ gap: 12 }}>
            <h2>Dependency</h2>
            <div className="path"><span className="chip">{byId[edge.source_component_id]?.name}</span><span className="arrow">depends on</span><span className="chip">{byId[edge.target_component_id]?.name}</span></div>
            <Field label="Type" help="Mandatory: the dependent cannot serve without it. Optional: it keeps working (reduced).">
              <select className="select" disabled={locked} value={edge.dependency_type} onChange={(e) => updateDependency(edge.id, { dependency_type: e.target.value })}><option>MANDATORY</option><option>OPTIONAL</option></select>
            </Field>
            <Field label="Configured backup (redundancy)" help="If the target fails and this backup is available, the dependency fails over to it. Only configured backups are used – nothing is assumed.">
              <select className="select" disabled={locked} value={edge.fallback_component_id || ""} onChange={(e) => updateDependency(edge.id, e.target.value ? { fallback_component_id: +e.target.value } : { clear_fallback: true })}>
                <option value="">No backup</option>
                {comps.filter((c) => c.id !== edge.source_component_id && c.id !== edge.target_component_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <button className="btn danger sm" disabled={locked} onClick={() => removeDependency(edge.id)}><LuUnlink />Remove dependency</button>
          </div>
        )}

        {tab === "details" && !sel && !edge && (
          <div className="side-section">
            <p className="muted small">Select a component or dependency to inspect and edit it. Components are listed below.</p>
            <div className="col mt12" style={{ gap: 4 }}>
              {comps.map((c) => (
                <button key={c.id} className="nav-item" style={{ background: "none", border: "none", font: "inherit", width: "100%" }} onClick={() => setSelected(c.id)}>
                  <TypeIcon type={c.component_type} /><span className="nav-label ellipsis">{c.name}</span><span className="spacer" /><Badge value={c.criticality} />
                </button>
              ))}
            </div>
          </div>
        )}

        {tab === "functionalities" && <Functionalities pid={pid} comps={comps} funcs={data.functionalities} locked={locked} onChange={refresh} />}

        {tab === "validation" && (
          <div className="side-section col" style={{ gap: 10 }}>
            <p className="muted small">Validation runs cycle detection (Johnson's algorithm), and checks missing, duplicate and self dependencies, invalid backups and isolated components.</p>
            {v.issues.length === 0 && <Callout kind="success">No issues. The dependency graph is a valid DAG.</Callout>}
            {v.issues.map((i: any, idx: number) => (
              <div key={idx} className="callout" style={{ cursor: i.component_ids?.length ? "pointer" : undefined }} onClick={() => i.component_ids?.[0] && setSelected(i.component_ids[0])}>
                <Badge value={i.level} /><div><div className="strong xs">{i.code}</div><div className="small">{i.message}</div></div>
              </div>
            ))}
          </div>
        )}

        {tab === "history" && (
          <div className="side-section">
            <p className="muted small mb12">Every edit is a command object (validated, executed, logged). Architecture commands can be undone.</p>
            {(history.data || []).map((h) => (
              <div key={h.id} className="list-item" style={{ padding: "8px 0" }}>
                <div className="row xs"><span className="mono faint">{h.command_name}</span><div className="spacer" />{h.status === "UNDONE" ? <Badge value="STOPPED" label="undone" /> : h.undoable ? <Badge value="INFO" label="undoable" /> : null}</div>
                <div className="small">{h.description}</div><div className="faint xs">{ago(h.created_at)}</div>
              </div>
            ))}
            {!history.data?.length && <span className="faint small">No commands yet.</span>}
          </div>
        )}
      </aside>

      {adding && (
        <Modal title="Add component" onClose={() => setAdding(false)} footer={<><button className="btn" onClick={() => setAdding(false)}>Cancel</button><button className="btn primary" onClick={addComponent}><LuPlus />Add component</button></>}>
          <ComponentForm value={newComp} onChange={setNewComp} />
        </Modal>
      )}
      {connect && (
        <Modal title="New dependency" onClose={() => setConnect(null)} footer={<><button className="btn" onClick={() => setConnect(null)}>Cancel</button><button className="btn primary" onClick={createDependency}><LuLink />Create dependency</button></>}>
          <div className="col" style={{ gap: 14 }}>
            <div className="path"><span className="chip">{byId[connect.source]?.name}</span><span className="arrow">depends on</span><span className="chip">{byId[connect.target]?.name}</span></div>
            <Field label="Dependency type"><select className="select" value={connect.dependency_type} onChange={(e) => setConnect({ ...connect, dependency_type: e.target.value })}><option value="MANDATORY">Mandatory – cannot serve without it</option><option value="OPTIONAL">Optional – keeps working without it</option></select></Field>
            <Field label="Configured backup (optional)"><select className="select" value={connect.fallback_id} onChange={(e) => setConnect({ ...connect, fallback_id: e.target.value })}>
              <option value="">No backup</option>{comps.filter((c) => c.id !== connect.source && c.id !== connect.target).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Callout>Connections that would create a circular dependency are rejected by the server.</Callout>
          </div>
        </Modal>
      )}
    </div>
  );
}

function AddDependency({ sel, comps, deps, onAdd }: { sel: any; comps: any[]; deps: any[]; onAdd: (target: number, type: string) => void }) {
  const [target, setTarget] = useState("");
  const [type, setType] = useState("MANDATORY");
  const candidates = comps.filter((c) => c.id !== sel.id && !deps.some((d) => d.source_component_id === sel.id && d.target_component_id === c.id));
  return (
    <div className="row mt8" style={{ gap: 6 }}>
      <select className="select sm" aria-label="New dependency target" value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="">Add dependency on…</option>{candidates.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <select className="select sm" style={{ width: 120 }} aria-label="Dependency type" value={type} onChange={(e) => setType(e.target.value)}><option>MANDATORY</option><option>OPTIONAL</option></select>
      <button className="btn sm icon" disabled={!target} aria-label="Add dependency" title="Add dependency" onClick={() => { onAdd(+target, type); setTarget(""); }}><LuPlus /></button>
    </div>
  );
}

function Functionalities({ pid, comps, funcs, locked, onChange }: { pid: number; comps: any[]; funcs: any[]; locked: boolean; onChange: () => void }) {
  const { toast, error, confirm } = useFeedback();
  const [edit, setEdit] = useState<any>(null);
  const save = async () => {
    if (!edit.name.trim() || !edit.component_ids.length) { toast("warning", "Enter a name and select at least one component"); return; }
    try {
      const body = { name: edit.name, description: edit.description, is_critical: edit.is_critical, component_ids: edit.component_ids };
      if (edit.id) await api.put(`/functionalities/${edit.id}`, body); else await api.post(`/projects/${pid}/functionalities`, body);
      toast("success", "Functionality saved");
      setEdit(null);
      onChange();
    } catch (e) { error(e); }
  };
  const remove = async (f: any) => {
    if (!await confirm({ title: "Delete functionality?", danger: true, message: `'${f.name}' will no longer be used in impact analysis.` })) return;
    try { await api.del(`/functionalities/${f.id}`); onChange(); } catch (e) { error(e); }
  };
  const name = (id: number) => comps.find((c) => c.id === id)?.name;
  return (
    <div className="side-section">
      <p className="muted small">A functionality is available only when every listed component is available. Critical ones weigh double in impact scoring.</p>
      <button className="btn sm mt12" disabled={locked} onClick={() => setEdit({ name: "", description: "", is_critical: false, component_ids: [] })}><LuPlus />Add functionality</button>
      <div className="mt12">
        {funcs.map((f) => (
          <div key={f.id} className="list-item" style={{ padding: "10px 0" }}>
            <div className="row"><span className="strong">{f.name}</span>{f.is_critical && <Badge value="CRITICAL" label="critical" />}<div className="spacer" />
              <button className="btn ghost sm" disabled={locked} onClick={() => setEdit({ ...f })}>Edit</button>
              <button className="btn ghost sm icon" disabled={locked} aria-label="Delete functionality" onClick={() => remove(f)}><LuTrash2 /></button></div>
            <div className="chips mt8">{f.component_ids.map((id: number) => <span key={id} className="chip">{name(id)}</span>)}</div>
          </div>
        ))}
      </div>
      {edit && (
        <Modal title={edit.id ? "Edit functionality" : "Add functionality"} onClose={() => setEdit(null)} footer={<><button className="btn" onClick={() => setEdit(null)}>Cancel</button><button className="btn primary" onClick={save}><LuCheck />Save</button></>}>
          <div className="col" style={{ gap: 12 }}>
            <Field label="Name"><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Description"><input className="input" value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            <label className="check"><input type="checkbox" checked={edit.is_critical} onChange={(e) => setEdit({ ...edit, is_critical: e.target.checked })} />Critical user-facing functionality</label>
            <div className="label">Required components</div>
            <div className="grid g2" style={{ gap: 6 }}>{comps.map((c) => (
              <label key={c.id} className="check"><input type="checkbox" checked={edit.component_ids.includes(c.id)}
                onChange={(e) => setEdit({ ...edit, component_ids: e.target.checked ? [...edit.component_ids, c.id] : edit.component_ids.filter((x: number) => x !== c.id) })} />{c.name}</label>
            ))}</div>
          </div>
        </Modal>
      )}
    </div>
  );
}
