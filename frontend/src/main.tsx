import { createRoot } from "react-dom/client";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  useNavigate,
  useParams,
  Link,
  Navigate,
} from "react-router";
import { api, terminal, settingsLabel, effortLabels } from "./api";
import type { Catalog, Job, JobSummary } from "./types";
import {
  renderReport,
  renderEvidence,
  fold,
  candidate,
  safeUrl,
} from "./report";
import { LocationMap, type MapHandle } from "./LocationMap";
import "leaflet/dist/leaflet.css";
import "./styles.css";
const message = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
function App() {
  const [pollVersion, setPollVersion] = useState(0);
  const { id } = useParams();
  const navigate = useNavigate();
  const [items, setItems] = useState<JobSummary[]>([]),
    [job, setJob] = useState<Job | null>(null),
    [notice, setNotice] = useState(""),
    [health, setHealth] = useState("Connecting to Codex…"),
    [drawer, setDrawer] = useState(false),
    [catalog, setCatalog] = useState<Catalog | null>(null),
    [model, setModel] = useState(""),
    [effort, setEffort] = useState(""),
    [settingsError, setSettingsError] = useState(""),
    [busy, setBusy] = useState(false),
    [file, setFile] = useState<File | null>(null),
    [preview, setPreview] = useState(""),
    [drag, setDrag] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    input = useRef<HTMLInputElement>(null),
    map = useRef<MapHandle>(null);
  const refresh = () =>
    api<JobSummary[]>("/api/jobs")
      .then(setItems)
      .catch((e) => setNotice(message(e)));
  async function loadSettings() {
    const data = await api<Catalog>("/api/settings");
    setCatalog(data);
    const selected =
      data.models.find((m) => m.id === data.settings.model) || data.models[0];
    setModel(selected?.id || "");
    setEffort(
      selected?.efforts.includes(data.settings.reasoning_effort)
        ? data.settings.reasoning_effort
        : selected?.efforts.includes("high")
          ? "high"
          : selected?.efforts[0] || "",
    );
  }
  useEffect(() => {
    let alive = true;
    api<{ codex_installed: boolean; authenticated: boolean }>("/api/health")
      .then((h) => {
        if (!alive) return;
        const ok = h.codex_installed && h.authenticated;
        setHealth(
          ok
            ? "Codex ready"
            : h.codex_installed
              ? "Connect Codex"
              : "Codex missing",
        );
        if (!ok)
          setNotice(
            h.codex_installed
              ? "Connect Codex using “codex login”, then reload this page."
              : "Install Codex CLI and sign in using “codex login”.",
          );
      })
      .catch(() => {
        if (alive) setHealth("Server unavailable");
      });
    loadSettings().catch((e) =>
      setNotice("Settings unavailable: " + message(e)),
    );
    void refresh();
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    document.body.classList.toggle("sidebar-open", drawer);
    return () => document.body.classList.remove("sidebar-open");
  }, [drawer]);
  useEffect(() => {
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawer(false);
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    setJob(null);
    setNotice("");
    document.body.classList.toggle("investigating", !!id);
    if (matchMedia("(max-width:760px)").matches) setDrawer(false);
    if (!id) {
      setFile(null);
      void refresh();
      return;
    }
    async function poll() {
      try {
        const data = await api<Job>("/api/jobs/" + id);
        if (!alive) return;
        setJob(data);
        if (!terminal(data.status)) timer = setTimeout(poll, 1800);
        else void refresh();
      } catch (e) {
        if (alive) {
          setNotice(message(e) + " Retrying in a few seconds.");
          timer = setTimeout(poll, 5000);
        }
      }
    }
    void poll();
    window.scrollTo({ top: 0 });
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, pollVersion]);
  useEffect(() => {
    if (!file) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  function select(value?: File) {
    if (!value) return;
    if (value.size > 25 * 1024 * 1024) {
      setNotice("The limit is 25 MB per image.");
      return;
    }
    setFile(value);
    setNotice("");
  }
  async function action(run: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await run();
    } catch (e) {
      setNotice(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function reportClick(e: MouseEvent) {
    const target = e.target;
    if (!(target instanceof Element)) return;
    const copy = target.closest<HTMLElement>("[data-copy-coordinates]");
    if (copy) {
      try {
        await navigator.clipboard.writeText(copy.dataset.copyCoordinates!);
        copy.textContent = "Copied ✓";
        setTimeout(() => {
          if (copy.isConnected) copy.textContent = "Copy coordinates";
        }, 1800);
      } catch {
        setNotice(
          "Copy unavailable. Select the coordinate link text to copy it.",
        );
      }
    }
    if (target.closest("[data-focus-coordinates]")) map.current?.focus();
  }
  const report = job?.report || job?.partial,
    past = job?.revisions?.slice(0, -1).reverse() || [];
  const efforts = catalog?.models.find((m) => m.id === model)?.efforts || [];
  return (
    <>
      <div
        id="history-drawer"
        className={"history-drawer" + (drawer ? " open" : "")}
        onPointerLeave={(e) => {
          if (
            e.pointerType === "mouse" &&
            !e.currentTarget.contains(document.activeElement)
          )
            setDrawer(false);
        }}
      >
        <button
          id="history-toggle"
          className="history-toggle secondary"
          aria-expanded={drawer}
          aria-controls="history-section"
          aria-label="Toggle investigations"
          onClick={() => setDrawer(!drawer)}
          onPointerEnter={(e) => {
            if (e.pointerType === "mouse") setDrawer(true);
          }}
        >
          {drawer ? "‹" : "›"}
        </button>
        <aside
          id="history-section"
          aria-label="Investigation history"
          inert={!drawer}
        >
          <div className="history-heading">
            <p className="eyebrow">INVESTIGATIONS</p>
            <button
              id="history-new"
              className="secondary"
              onClick={() => {
                navigate("/");
                if (matchMedia("(max-width:760px)").matches) setDrawer(false);
              }}
            >
              New investigation +
            </button>
          </div>
          <div id="history">
            {items.map((j) => (
              <div
                key={j.id}
                className={"history-row" + (id === j.id ? " active" : "")}
              >
                <Link
                  className="history-item"
                  to={"/investigations/" + j.id}
                  aria-current={id === j.id ? "page" : undefined}
                >
                  <strong>{j.filename}</strong>
                  <span>
                    {new Date(j.created_at).toLocaleString("en-GB")} ·{" "}
                    {(
                      {
                        completed: "Completed",
                        running: "Running",
                        pending: "Preparing",
                        error: "Error",
                        cancelled: "Stopped",
                      } as Record<string, string>
                    )[j.status] || j.status}
                  </span>
                </Link>
                <button
                  className="history-delete"
                  disabled={busy}
                  title="Delete this investigation"
                  aria-label={"Delete investigation " + j.filename}
                  onClick={() => {
                    if (
                      confirm(
                        "Delete this investigation et ses fichiers ? Une analyse en cours sera interrompue.",
                      )
                    )
                      void action(async () => {
                        await api("/api/jobs/" + j.id, { method: "DELETE" });
                        if (id === j.id) navigate("/");
                        await refresh();
                      });
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <p id="history-empty" hidden={!!items.length}>
            No investigations yet.
          </p>
        </aside>
      </div>
      <header>
        <Link className="brand" to="/" aria-label="Codex Find Place home">
          <img className="brand-logo" src="/static/logo.png" alt="" /> Codex{" "}
          <strong>Find Place</strong>
        </Link>
        <nav>
          <button
            id="settings-open"
            className="secondary"
            aria-haspopup="dialog"
            onClick={() =>
              void action(async () => {
                await loadSettings();
                setSettingsError("");
                dialog.current?.showModal();
              })
            }
          >
            Settings
          </button>
        </nav>
        <span
          id="engine"
          className={
            "engine " + (health === "Codex ready" ? "ready" : "offline")
          }
        >
          <i />
          {health}
        </span>
      </header>
      <dialog
        ref={dialog}
        id="settings-dialog"
        aria-labelledby="settings-title"
      >
        <form
          id="settings-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await api("/api/settings", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model, reasoning_effort: effort }),
              });
              await loadSettings();
              dialog.current?.close();
            } catch (error) {
              setSettingsError(message(error));
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="dialog-heading">
            <h2 id="settings-title">Codex settings</h2>
            <button
              id="settings-close"
              type="button"
              className="text-button"
              aria-label="Close settings"
              onClick={() => dialog.current?.close()}
            >
              ×
            </button>
          </div>
          <p>
            These settings apply to new investigations and further research.
          </p>
          <label htmlFor="model">Model</label>
          <select
            id="model"
            required
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
              const values =
                catalog?.models.find((m) => m.id === e.target.value)?.efforts ||
                [];
              setEffort(
                values.includes(effort)
                  ? effort
                  : values.includes("high")
                    ? "high"
                    : values[0] || "",
              );
            }}
          >
            {catalog?.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
          <small id="model-help">
            Models and reasoning levels come from your Codex catalog.
          </small>
          <label htmlFor="reasoning">Reasoning effort</label>
          <select
            id="reasoning"
            value={effort}
            onChange={(e) => setEffort(e.target.value)}
          >
            {efforts.map((v) => (
              <option key={v} value={v}>
                {effortLabels[v] || v}
              </option>
            ))}
          </select>
          <small>
            Higher reasoning effort may take longer and use more Codex quota.
          </small>
          <small>
            AI follows promising leads and stops when the location is verified
            or no useful checks remain.
          </small>
          <p
            id="settings-error"
            className="error"
            hidden={!settingsError}
            role="alert"
          >
            {settingsError}
          </p>
          <button
            id="settings-save"
            className="primary"
            type="submit"
            disabled={busy || !efforts.length}
          >
            Save settings
          </button>
        </form>
      </dialog>
      <main>
        <section className="intro">
          <p className="eyebrow">AI-POWERED VISUAL INTELLIGENCE</p>
          <h1>
            Find the place.
            <br />
            Pin the viewpoint.
          </h1>
          <p className="lead">
            Upload a photo. Let AI trace the clues,
            <br className="desktop" /> verify the location and pinpoint the
            viewpoint.
          </p>
        </section>
        <section
          id="upload-section"
          className="upload-section"
          aria-label="Upload a photo"
        >
          <label
            id="dropzone"
            className={"dropzone" + (drag ? " drag" : "")}
            htmlFor="file"
            hidden={!!file}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              select(e.dataTransfer.files[0]);
            }}
          >
            <input
              ref={input}
              id="file"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/tiff,image/avif"
              onChange={(e) => select(e.target.files?.[0])}
            />
            <span className="upload-icon">↥</span>
            <strong id="file-label">Drop your image here</strong>
            <span id="file-hint">or click to browse files</span>
            <span className="formats">
              JPEG, PNG, WebP, TIFF, AVIF · 25 MB maximum
            </span>
          </label>
          <div id="selected" hidden={!file}>
            <img
              id="selected-preview"
              src={preview || undefined}
              alt="Selected image"
            />
            <div>
              <strong id="selected-name">{file?.name}</strong>
              <button
                id="remove"
                className="text-button"
                type="button"
                onClick={() => {
                  setFile(null);
                  if (input.current) input.current.value = "";
                }}
              >
                Change image
              </button>
            </div>
          </div>
          <button
            id="analyze"
            className="primary"
            disabled={!file || busy}
            onClick={() =>
              void action(async () => {
                if (!file) return;
                const data = new FormData();
                data.append("file", file);
                const result = await api<{ id: string }>("/api/jobs", {
                  method: "POST",
                  body: data,
                });
                navigate("/investigations/" + result.id);
                await refresh();
              })
            }
          >
            Locate image <span>↗</span>
          </button>
          <p id="settings-summary" className="settings-summary">
            {catalog && settingsLabel(catalog.settings)}
          </p>
          <p className="privacy">
            Powered by your Codex account · Image shared with the model
            <br />
            Files and results are stored on this computer.
          </p>
        </section>
        <p id="notice" role="alert" hidden={!notice}>
          {notice}
        </p>
        <section
          id="investigation"
          hidden={!id}
          aria-label="Active investigation"
        >
          <div className="work-heading">
            <div>
              <p className="eyebrow">INVESTIGATION WORKSPACE</p>
              <h2 id="job-title">
                {job?.status === "completed"
                  ? "What this image reveals"
                  : job && terminal(job.status)
                    ? "Investigation stopped"
                    : "Investigation in progress"}
              </h2>
            </div>
            <button
              id="new"
              className="secondary"
              onClick={() => navigate("/")}
            >
              New image
            </button>
          </div>
          {job && (
            <div className="workspace">
              <aside>
                <img
                  id="job-preview"
                  hidden={!job.metadata}
                  src={job.metadata ? `/api/jobs/${job.id}/preview` : undefined}
                  alt="Photo under investigation"
                />
                <div className="file-details" id="file-details">
                  {job.metadata &&
                    `${job.filename} · ${job.metadata.width} × ${job.metadata.height} · ${(job.metadata.bytes / 1024 / 1024).toFixed(2)} MB`}
                </div>
                <p id="job-settings" className="settings-summary">
                  {job.settings
                    ? settingsLabel(job.settings)
                    : "Older investigation: model was not recorded."}
                </p>
                <div className="progress-box">
                  <div className="progress-label">
                    <span id="stage">{job.stage}</span>
                    <span id="percent">{job.progress} %</span>
                  </div>
                  <progress id="progress" max="100" value={job.progress} />
                  <p id="elapsed">
                    Started at{" "}
                    {new Date(job.created_at).toLocaleTimeString("en-GB", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · progress by stage
                  </p>
                  <ol id="timeline">
                    {job.events
                      .slice(-7)
                      .reverse()
                      .map((ev, i) => (
                        <li key={i}>{ev.message}</li>
                      ))}
                  </ol>
                  <button
                    id="cancel"
                    className="text-button"
                    hidden={terminal(job.status)}
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        setJob(
                          await api<Job>(`/api/jobs/${id}/cancel`, {
                            method: "POST",
                          }),
                        );
                      })
                    }
                  >
                    Stop analysis
                  </button>
                </div>
                <a
                  id="export"
                  className="secondary export"
                  href={`/api/jobs/${id}/export`}
                  download
                >
                  Export investigation JSON ↓
                </a>
              </aside>
              <div className="findings" onClick={reportClick}>
                <div
                  id="report"
                  aria-live="polite"
                  dangerouslySetInnerHTML={{
                    __html: report ? renderReport(report, !job.report) : "",
                  }}
                />
                <LocationMap key={id} ref={map} job={job} />
                <div
                  id="report-details"
                  dangerouslySetInnerHTML={{
                    __html: report ? renderEvidence(report) : "",
                  }}
                />
                <div className="deepen-row">
                  <button
                    id="deepen"
                    className="secondary"
                    hidden={!terminal(job.status) || !report}
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        await api(`/api/jobs/${id}/deepen`, { method: "POST" });
                        setPollVersion((v) => v + 1);
                        await refresh();
                      })
                    }
                  >
                    Research further ↗
                  </button>
                  <p id="deepen-hint" hidden={!terminal(job.status) || !report}>
                    Continue from saved evidence and preserve the investigation
                    history. Camera positions are refined only when a concrete
                    verification remains.
                  </p>
                </div>
                <div
                  id="working"
                  className="working"
                  hidden={!!report || terminal(job.status)}
                >
                  <span className="pulse" />
                  <h3>Decoding the scene.</h3>
                  <p>
                    AI examines visual clues, verifies sources and compares
                    reference photos. Search focuses on the camera position once
                    the site is recognized; difficult cases may take longer.
                  </p>
                  <p>
                    You can close this page. Analysis continues while the server
                    is running.
                  </p>
                </div>
                <div
                  id="job-error"
                  className="error"
                  hidden={!job.error}
                  role="alert"
                >
                  {job.error}
                </div>
                <details id="revisions-panel" hidden={!past.length}>
                  <summary>Previous stages · newest first</summary>
                  <div
                    id="revisions"
                    dangerouslySetInnerHTML={{
                      __html: past
                        .map((r) =>
                          fold(
                            r.stage +
                              " · " +
                              new Date(r.time || "").toLocaleString("en-GB"),
                            "<p>" +
                              r.report.conclusion.replace(
                                /[&<>]/g,
                                (c) =>
                                  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[
                                    c
                                  ]!,
                              ) +
                              "</p>" +
                              candidate(r.report.best_candidate),
                          ),
                        )
                        .join(""),
                    }}
                  />
                </details>
                <details
                  id="references-panel"
                  hidden={
                    !job.references?.length && !job.reference_batches?.length
                  }
                >
                  <summary>Reference photos</summary>
                  <p>
                    Public photos downloaded for comparison. Their presence
                    alone does not confirm a location.
                  </p>
                  <div id="references" className="reference-grid">
                    {job.references?.map((r) => (
                      <figure key={r.id} className="reference-card">
                        <img
                          loading="lazy"
                          src={`/api/jobs/${id}/references/${encodeURIComponent(r.id)}`}
                          alt={r.title}
                        />
                        <figcaption>
                          {safeUrl(r.page_url) ? (
                            <a
                              target="_blank"
                              rel="noopener noreferrer"
                              href={safeUrl(r.page_url)!}
                            >
                              {r.id} · {r.title} ↗
                            </a>
                          ) : (
                            r.title
                          )}
                          <small>
                            {r.author} ·{" "}
                            {safeUrl(r.license_url) ? (
                              <a
                                target="_blank"
                                rel="noopener noreferrer"
                                href={safeUrl(r.license_url)!}
                              >
                                {r.license}
                              </a>
                            ) : (
                              r.license
                            )}
                          </small>
                          <small>Search: {r.query}</small>
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                  <div id="reference-errors">
                    {job.reference_batches
                      ?.filter((b) => b.errors?.length)
                      .map((b, i) => (
                        <p key={i} className="reference-error">
                          {b.stage} : {b.errors?.join(" · ")}
                        </p>
                      ))}
                  </div>
                </details>
                <details id="metadata-panel" hidden={!job.metadata}>
                  <summary>Metadata and technical details</summary>
                  <pre id="metadata">
                    {JSON.stringify(job.metadata, null, 2)}
                  </pre>
                </details>
                <details id="solar-panel" hidden={!job.solar}>
                  <summary>Astronomical verification</summary>
                  <pre id="solar">{JSON.stringify(job.solar, null, 2)}</pre>
                </details>
              </div>
            </div>
          )}
        </section>
      </main>
      <footer>
        <span>Observe. Compare. Locate.</span>
        <span>Precision follows evidence.</span>
      </footer>
    </>
  );
}
const legacy = location.hash.match(/^#enquete=([a-f0-9]{32})$/);
if (legacy) history.replaceState(null, "", "/investigations/" + legacy[1]);
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<App />} />
      <Route path="/investigations/:id" element={<App />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </BrowserRouter>,
);
