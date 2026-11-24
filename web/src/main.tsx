import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Choice = { digit: string; label: string; target: string };
type Node = {
  id: string;
  type: "menu" | "message" | "provider" | "end";
  lines?: string[];
  prompt?: string;
  choices?: Choice[];
  continue?: Choice;
  onTimeout?: string;
  operation?: string;
  args?: Record<string, string>;
  bind?: string;
  onOk?: string;
  onUnavailable?: string;
};
type Graph = { schemaVersion: number; entry: string; nodes: Node[] };
type Application = { id: string; name: string; generation: number; archived: boolean; draft: Graph };
type Revision = { id: string; generation: number; created_at: string };
type Simulation = {
  id: string; node: string; lines: string[]; choices: Choice[]; prompt: string;
  page?: number; pageCount?: number; ended: boolean; trace: string[];
};
type Settings = { value: Record<string, unknown>; generation: number };
type Route = { name: string; revision_id: string | null };
type Point = { x: number; y: number };

const operations: Record<string, string> = {
  "weather.current": "site", "weather.forecast": "site", "news.headlines": "topic",
  "market.quote": "instrument", "lottery.draw": "game", "assistant.answer": "question",
};
const titles = { menu: "Menu", message: "Screen", provider: "Data", end: "Hang up" };

async function api<T>(path: string, method = "GET", body?: unknown, generation?: number): Promise<T> {
  const headers: Record<string, string> = { "X-Coinline-CSRF": "request" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (generation !== undefined) headers["If-Match"] = `"${generation}"`;
  const response = await fetch(`/api/v1${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const { detail } = await response.json();
    throw new Error(Array.isArray(detail)
      ? detail.map((entry) => `${entry.path ?? ""} ${entry.message ?? entry.msg}`).join("\n")
      : detail ?? "Request failed.");
  }
  const raw = await response.text();
  return (raw ? JSON.parse(raw) : undefined) as T;
}

function targets(node: Node) {
  return [...(node.choices?.map(({ target }) => target) ?? []),
    node.continue?.target, node.onOk, node.onUnavailable, node.onTimeout]
    .filter((item): item is string => Boolean(item));
}

function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [oidc, setOidc] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState<"apps" | "setup">("apps");
  const [apps, setApps] = useState<Application[]>([]);
  const [loaded, setLoaded] = useState<Application>();
  const [draft, setDraft] = useState<Graph>();
  const [nodeId, setNodeId] = useState("");
  const [coordinates, setCoordinates] = useState<Record<string, Point>>({});
  const [revision, setRevision] = useState<Revision[]>([]);
  const [stage, setStage] = useState<Simulation>();
  const [fault, setFault] = useState("");
  const [settings, setSettings] = useState<Settings>();
  const [configuration, setConfiguration] = useState("");
  const [routes, setRoutes] = useState<Route[]>([]);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const chosen = draft?.nodes.find((node) => node.id === nodeId);

  async function action(callback: () => Promise<void>) {
    setError(""); setStatus(""); setBusy(true);
    try { await callback(); } catch (exception) {
      setError(exception instanceof Error ? exception.message : "The request failed.");
    } finally { setBusy(false); }
  }
  async function select(id: string) {
    const [detail, revisions] = await Promise.all([
      api<Application>(`/apps/${id}/draft`), api<Revision[]>(`/apps/${id}/revisions`),
    ]);
    setLoaded(detail); setDraft(detail.draft); setRevision(revisions); setStage(undefined);
    setNodeId(detail.draft.entry); setCoordinates({});
  }
  async function refresh() {
    const list = await api<Application[]>("/apps");
    setApps(list);
    if (!loaded && list.length) await select(list[0].id);
  }
  useEffect(() => {
    api("/session").then(() => setAuthenticated(true)).catch(() => {});
    api<{ oidc: boolean }>("/session/mode").then((mode) => setOidc(mode.oidc)).catch(() => {});
  }, []);
  useEffect(() => { if (authenticated) void action(refresh); }, [authenticated]);
  function edit(change: Partial<Node>) {
    if (draft && chosen) setDraft({ ...draft, nodes: draft.nodes.map((node) =>
      node.id === chosen.id ? { ...node, ...change } : node) });
  }
  function add(type: Node["type"]) {
    if (!draft) return;
    let index = 1;
    while (draft.nodes.some((node) => node.id === `${type}-${index}`)) index++;
    const id = `${type}-${index}`;
    const end = draft.nodes.find((node) => node.type === "end")?.id ?? draft.entry;
    const back = { digit: "0", label: "Back", target: end };
    const fields = type === "end" ? { prompt: "Goodbye." } :
      type === "provider" ? { operation: "weather.current", args: { site: "demo-harbour" },
        bind: id, onOk: end, onUnavailable: end } :
      { lines: ["New screen"], prompt: "Press zero to exit.", onTimeout: end,
        ...(type === "menu" ? { choices: [back] } : { continue: back }) };
    setDraft({ ...draft, nodes: [...draft.nodes, { id, type, ...fields }] }); setNodeId(id);
  }
  function save() {
    if (!loaded || !draft) return Promise.resolve();
    return api<Application>(`/apps/${loaded.id}/draft`, "PUT", { graph: draft }, loaded.generation)
      .then((value) => { setLoaded(value); setDraft(value.draft); setStatus("Draft saved."); });
  }
  function editTargets(selected: string | undefined, update: (target: string) => void) {
    return <select value={selected} onChange={(event) => update(event.target.value)}>
      {draft?.nodes.map(({ id }) => <option key={id}>{id}</option>)}
    </select>;
  }
  function layout(id: string): Point {
    const index = draft?.nodes.findIndex((node) => node.id === id) ?? 0;
    return coordinates[id] ?? { x: 28 + (index % 3) * 154, y: 24 + Math.floor(index / 3) * 82 };
  }
  async function simEvent(event: { digit?: string; timeout?: boolean; hangup?: boolean }) {
    if (stage) setStage(await api(`/simulations/${stage.id}/events`, "POST", event));
  }
  async function showSetup() {
    const [config, routeList] = await Promise.all([api<Settings>("/providers"), api<Route[]>("/routes")]);
    setSettings(config); setConfiguration(JSON.stringify(config.value, null, 2)); setRoutes(routeList); setPage("setup");
  }

  if (!authenticated) return <main className="login">
    <div className="mark" aria-hidden="true">CL</div><h1>CoinLine ADSI</h1>
    {oidc ? <a href="/auth/login?console=true">Sign in with your identity provider</a> :
    <form onSubmit={(event) => { event.preventDefault(); void action(async () => {
      await api("/session", "POST", { password }); setPassword(""); setAuthenticated(true);
    }); }}>
      <label>Console access code<input type="password" autoComplete="current-password" value={password}
        onChange={(event) => setPassword(event.target.value)} required /></label>
      <button className="primary" disabled={busy}>Sign in</button>
      {error && <p role="alert">{error}</p>}
    </form>}
  </main>;

  return <>
    <header className="top"><span className="mark" aria-hidden="true">CL</span><strong>CoinLine ADSI</strong>
      <nav aria-label="Main navigation">
        <button aria-current={page === "apps" ? "page" : undefined} onClick={() => setPage("apps")}>Applications</button>
        <button aria-current={page === "setup" ? "page" : undefined} onClick={() => void action(showSetup)}>Setup</button>
      </nav>
      <button className="quiet" onClick={() => void action(async () => {
        await api("/session", "DELETE"); setLoaded(undefined); setDraft(undefined); setAuthenticated(false);
      })}>Sign out</button>
    </header>
    {error && <pre className="notice error" role="alert">{error}</pre>}
    {status && <p className="notice" role="status">{status}</p>}
    {page === "setup" && <main className="setup">
      <h1>Setup</h1>
      <section className="panel"><h2>Incoming routes</h2><dl><dt>6500</dt><dd>ADSI lab exchange</dd>
        <dt>6501</dt><dd>{routes[0]?.revision_id ? "Published InfoLine revision" : "No active application"}</dd></dl></section>
      <section className="panel"><h2>Data providers</h2>
        <label>Provider configuration<textarea rows={15} value={configuration} spellCheck={false}
          onChange={(event) => setConfiguration(event.target.value)} /></label>
        <div className="actions">
          <button disabled={busy} onClick={() => void action(async () => {
            await api("/providers/test", "POST", JSON.parse(configuration)); setStatus("Configuration is valid.");
          })}>Validate</button>
          <button className="primary" disabled={busy} onClick={() => void action(async () => {
            if (!settings) return;
            const value = JSON.parse(configuration);
            const result = await api<{ generation: number }>("/providers", "PUT", value, settings.generation);
            setSettings({ value, generation: result.generation }); setStatus("Configuration saved.");
          })}>Apply</button>
        </div>
      </section>
    </main>}
    {page === "apps" && <main className="workspace">
      <aside className="catalogue">
        <h2>Applications</h2>
        <ul>{apps.map((entry) => <li key={entry.id}>
          <button className={loaded?.id === entry.id ? "selected" : ""}
            onClick={() => void action(() => select(entry.id))}>{entry.name}{entry.archived && " (archived)"}</button>
        </li>)}</ul>
        <form onSubmit={(event) => { event.preventDefault(); void action(async () => {
          const item = await api<Application>("/apps", "POST", { name: newName });
          await refresh(); await select(item.id); setNewName("");
        }); }}>
          <label>Application name<input value={newName} maxLength={80} required
            onChange={(event) => setNewName(event.target.value)} /></label>
          <button disabled={busy}>New application</button>
        </form>
        <label className="import">Import graph<input type="file" accept=".json,application/json"
          onChange={(event) => { const file = event.target.files?.[0]; if (file) void action(async () => {
            const item = await api<Application>("/apps/import", "POST",
              { name: file.name.replace(/\.json$/, "").slice(0, 80), graph: JSON.parse(await file.text()) });
            await refresh(); await select(item.id);
          }); }} /></label>
      </aside>
      {draft && loaded && <section className="editor">
        <div className="editor-head"><div><h1>{loaded.name}</h1><span>Draft {loaded.generation}</span></div>
          <div className="actions">
            <button disabled={busy || loaded.archived} onClick={() => void action(save)}>Save</button>
            <button className="primary" disabled={busy || loaded.archived} onClick={() => void action(async () => {
              await api(`/apps/${loaded.id}/revisions`, "POST", { routes: ["infoline"] }, loaded.generation);
              setRevision(await api(`/apps/${loaded.id}/revisions`)); setStatus("Saved draft published to 6501.");
            })}>Publish saved draft</button>
          </div>
        </div>
        <div className="toolbar"><strong>Add</strong>
          {(Object.keys(titles) as Node["type"][]).map((type) => <button key={type} disabled={loaded.archived}
            onClick={() => add(type)}>{titles[type]}</button>)}
        </div>
        <div className="canvas" style={{ minHeight: Math.max(205, Math.ceil(draft.nodes.length / 3) * 82 + 26) }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            const id = event.dataTransfer.getData("text/plain");
            if (!draft.nodes.some((node) => node.id === id)) return;
            const bounds = event.currentTarget.getBoundingClientRect();
            setCoordinates({ ...coordinates, [id]: {
              x: Math.max(5, Math.min(bounds.width - 134, event.clientX - bounds.x - 40)),
              y: Math.max(5, Math.min(bounds.height - 56, event.clientY - bounds.y - 20)),
            } });
          }}>
          <svg className="edges" aria-hidden="true">
            {draft.nodes.flatMap((node) => [...new Set(targets(node))].flatMap((target) => {
              if (!draft.nodes.some((item) => item.id === target)) return [];
              const a = layout(node.id), b = layout(target), mid = (a.x + b.x) / 2 + 60;
              return [<path key={`${node.id}/${target}`}
                d={`M ${a.x + 116} ${a.y + 23} C ${mid} ${a.y + 23}, ${mid} ${b.y + 23}, ${b.x} ${b.y + 23}`} />];
            }))}
          </svg>
          {draft.nodes.map((node) => <button key={node.id} draggable
            className={`graph-node ${node.type} ${node.id === nodeId ? "current" : ""}`}
            style={{ left: layout(node.id).x, top: layout(node.id).y }}
            onDragStart={(event) => event.dataTransfer.setData("text/plain", node.id)}
            onClick={() => setNodeId(node.id)}>
            <span>{node.id === draft.entry ? "Start / " : ""}{titles[node.type]}</span><strong>{node.id}</strong>
          </button>)}
        </div>
        {chosen && <section className="panel properties">
          <div className="editor-head"><h2>{chosen.id}</h2><button disabled={chosen.id === draft.entry}
            onClick={() => setDraft({ ...draft, entry: chosen.id })}>Set start</button></div>
          {chosen.lines && <label>Display lines<textarea rows={4} value={chosen.lines.join("\n")}
            onChange={(event) => edit({ lines: event.target.value.split("\n") })} /></label>}
          {chosen.type !== "provider" && <label>Voice prompt<textarea rows={2} value={chosen.prompt ?? ""}
            onChange={(event) => edit({ prompt: event.target.value })} /></label>}
          {(chosen.choices ?? (chosen.continue ? [chosen.continue] : [])).map((choice, index) => {
            const change = (update: Partial<Choice>) => chosen.choices
              ? edit({ choices: chosen.choices.map((old, i) => i === index ? { ...old, ...update } : old) })
              : edit({ continue: { ...choice, ...update } });
            return <div className="choice" key={index}>
              <label>Digit<input value={choice.digit} maxLength={1} onChange={(event) => change({ digit: event.target.value })} /></label>
              <label>Key label<input value={choice.label} maxLength={18} onChange={(event) => change({ label: event.target.value })} /></label>
              <label>Target{editTargets(choice.target, (target) => change({ target }))}</label>
              {chosen.choices && chosen.choices.length > 1 && <button onClick={() =>
                edit({ choices: chosen.choices?.filter((_, i) => i !== index) })}>Remove</button>}
            </div>;
          })}
          {chosen.choices && chosen.choices.length < 6 && <button onClick={() => edit({
            choices: [...chosen.choices!, { digit: "1", label: "Continue", target: draft.entry }],
          })}>Add choice</button>}
          {chosen.onTimeout && <label>On timeout{editTargets(chosen.onTimeout, (onTimeout) => edit({ onTimeout }))}</label>}
          {chosen.operation && <>
            <label>Data operation<select value={chosen.operation} onChange={(event) => edit({
              operation: event.target.value, args: { [operations[event.target.value]]: "" },
            })}>{Object.keys(operations).map((operation) => <option key={operation}>{operation}</option>)}</select></label>
            <label>Catalogue entry<input value={chosen.args?.[operations[chosen.operation]] ?? ""}
              onChange={(event) => edit({ args: { ...chosen.args, [operations[chosen.operation!]]: event.target.value } })} /></label>
            <label>Bind as<input value={chosen.bind} onChange={(event) => edit({ bind: event.target.value })} /></label>
            <label>On success{editTargets(chosen.onOk, (onOk) => edit({ onOk }))}</label>
            <label>On unavailable{editTargets(chosen.onUnavailable, (onUnavailable) => edit({ onUnavailable }))}</label>
          </>}
          <button disabled={draft.nodes.length < 2 || chosen.id === draft.entry} onClick={() => {
            setDraft({ ...draft, nodes: draft.nodes.filter((node) => node.id !== chosen.id) }); setNodeId(draft.entry);
          }}>Remove node</button>
        </section>}
        <details className="panel"><summary>Revisions and application settings</summary>
          <form onSubmit={(event) => {
            event.preventDefault(); const name = String(new FormData(event.currentTarget).get("name"));
            void action(async () => { setLoaded(await api(`/apps/${loaded.id}`, "PATCH", { name }, loaded.generation)); await refresh(); });
          }}><label>Name<input name="name" defaultValue={loaded.name} key={loaded.id} required maxLength={80} /></label>
          <button>Rename</button></form>
          <ul>{revision.map((item) => <li key={item.id}>Revision {item.generation} <button disabled={loaded.archived}
            onClick={() => void action(async () => {
              await api(`/apps/${loaded.id}/activate`, "POST", { revision: item.id, routes: ["infoline"] });
              setStatus(`Revision ${item.generation} is active on 6501.`);
            })}>Activate</button></li>)}</ul>
          <a href={`/api/v1/apps/${loaded.id}/export`} download={`${loaded.name}.json`}>Export saved graph</a>
          <button onClick={() => void action(async () => {
            await api(`/apps/${loaded.id}/${loaded.archived ? "restore" : "archive"}`, "POST",
              loaded.archived ? undefined : { disable_routes: true }); await refresh(); await select(loaded.id);
          })}>{loaded.archived ? "Restore" : "Archive and disable routes"}</button>
        </details>
      </section>}
      <aside className="preview">
        <h2>Handset simulator</h2>
        <div className="phone">
          <div className="display" aria-label="Terminal display" aria-live="polite">
            {(stage?.lines ?? chosen?.lines?.slice(0, 4) ?? ["READY"]).map((line, index) => <div key={index}>{line}</div>)}
            {stage?.ended && <div>CALL ENDED</div>}
          </div>
          <div className="keys">{Array.from({ length: 6 }, (_, index) => {
            const choice = stage?.choices[index];
            return <button key={index} disabled={!choice || busy} aria-label={choice?.label ?? "Unassigned softkey"}
              onClick={() => { if (choice) void action(() => simEvent({ digit: choice.digit })); }}>{choice?.label ?? "·"}</button>;
          })}</div>
          <div className="keypad">{Array.from("123456789*0#").map((digit) => <button key={digit}
            disabled={!stage || stage.ended || busy} onClick={() => void action(() => simEvent({ digit }))}>{digit}</button>)}</div>
        </div>
        <label>Fixture response<select value={fault} onChange={(event) => setFault(event.target.value)}>
          <option value="">Normal</option><option>stale</option><option>unavailable</option>
        </select></label>
        <div className="actions"><button className="primary" disabled={!draft || busy} onClick={() => void action(async () => {
          setStage(await api("/simulations", "POST", { graph: draft, fault: fault || null }));
        })}>Run draft</button>
        <button disabled={!stage || stage.ended || busy} onClick={() => void action(() => simEvent({ timeout: true }))}>Timeout</button>
        <button disabled={!stage || stage.ended || busy} onClick={() => void action(() => simEvent({ hangup: true }))}>Hang up</button></div>
        {stage && <section className="trace"><h3>Call trace</h3><p>{[...stage.trace, stage.node].join(" → ")}</p>
          {stage.page && <p>Page {stage.page} of {stage.pageCount}</p>}
          {stage.prompt && <><h3>Voice prompt</h3><p>{stage.prompt}</p></>}
        </section>}
      </aside>
    </main>}
  </>;
}

createRoot(document.getElementById("root")!).render(<App />);
