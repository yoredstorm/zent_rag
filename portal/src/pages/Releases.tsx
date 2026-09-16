import {
  ArrowCounterClockwise,
  CaretDown,
  GitBranch,
  Heartbeat,
  Pause,
  Play,
  RocketLaunch,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Timeline, type TimelineItem } from "../components/Timeline";
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  KeyValue,
  Menu,
  MenuItem,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  StatusBadge,
  SuccessInline,
  menuItemClass,
  type Column,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Version = {
  id: string;
  version_number: number;
  status: string;
  notes: string | null;
  created_at: string;
};
type Release = {
  id: string;
  agent_id: string;
  version_id: string;
  version_number: number;
  channel: string;
  traffic_pct: number;
  status: string;
  health_score: number | null;
  created_at: string;
  events?: { id: string; event_type: string; detail: string; created_at: string }[];
};
type Diff = {
  version_a: { number: number };
  version_b: { number: number };
  config_diff: { key: string; kind: string; a: unknown; b: unknown }[];
  prompt_diff: { changed: boolean; a_chars: number; b_chars: number };
  model_changed: boolean;
  tools_changed: boolean;
};

const RELEASE_ACTIONS = [
  { action: "health", label: "Consultar health", icon: Heartbeat },
  { action: "promote", label: "Promover", icon: RocketLaunch },
  { action: "rollback", label: "Rollback", icon: ArrowCounterClockwise },
  { action: "pause", label: "Pausar", icon: Pause },
  { action: "resume", label: "Reanudar", icon: Play },
] as const;

function diffTone(kind: string): "warn" | "ok" | "danger" {
  if (kind === "changed") return "warn";
  if (kind === "added") return "ok";
  return "danger";
}

export default function ReleasesPage() {
  const { session } = useAuth();
  const [releases, setReleases] = useState<Release[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);
  const [agentId, setAgentId] = useState("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [startForm, setStartForm] = useState({ version_id: "", channel: "canary", traffic_pct: 50 });
  const [diff, setDiff] = useState<Diff | null>(null);
  const [diffPair, setDiffPair] = useState({ a: "", b: "" });
  const [detail, setDetail] = useState<Release | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, a] = await Promise.all([
        api<{ releases: Release[] }>("/api/v1/releases", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ agents: { id: string; name: string }[] }>("/api/v1/agents", {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ agents: [] })),
      ]);
      setReleases(r.releases || []);
      setAgents(a.agents || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function loadVersions(aid: string) {
    if (!session) return;
    const v = await api<{ versions: Version[] }>(`/api/v1/releases/versions/${aid}`, {
      token: session.token,
      organizationId: session.organizationId,
    });
    setVersions(v.versions || []);
  }

  async function start() {
    if (!session || !agentId) return;
    setBusy("start");
    setError("");
    setMsg("");
    try {
      const out = await api<{ release_id: string }>("/api/v1/releases/start", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ agent_id: agentId, ...startForm }),
      });
      setMsg(`Release ${out.release_id.slice(0, 8)}… iniciado.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(
    releaseId: string,
    action: "health" | "promote" | "rollback" | "pause" | "resume",
  ) {
    if (!session) return;
    setBusy(`${action}-${releaseId.slice(0, 6)}`);
    setError("");
    setMsg("");
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/releases/${releaseId}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`${action}: ${JSON.stringify(out).slice(0, 120)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(releaseId: string) {
    if (!session) return;
    const d = await api<Release>(`/api/v1/releases/${releaseId}`, {
      token: session.token,
      organizationId: session.organizationId,
    });
    setDetail(d);
  }

  async function showDiff() {
    if (!session || !agentId || !diffPair.a || !diffPair.b) return;
    setError("");
    try {
      const d = await api<Diff>(
        `/api/v1/releases/diff/${agentId}?a=${diffPair.a}&b=${diffPair.b}`,
        { token: session.token, organizationId: session.organizationId },
      );
      setDiff(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const columns: Column<Release>[] = [
    {
      key: "version",
      header: "Versión",
      render: (r) => (
        <div className="min-w-0">
          <p className="text-[13.5px] text-text">
            v{r.version_number}{" "}
            <span className="mono text-[11px] text-faint">{r.id.slice(0, 8)}</span>
          </p>
          <p className="mt-0.5 text-xs text-muted">{fmtDateTime(r.created_at)}</p>
        </div>
      ),
    },
    {
      key: "channel",
      header: "Canal",
      render: (r) => (
        <Badge tone={r.channel === "canary" ? "info" : "neutral"}>{r.channel}</Badge>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: "traffic",
      header: "Tráfico",
      align: "right",
      hideBelow: "md",
      render: (r) => <span className="mono text-xs text-muted">{r.traffic_pct}%</span>,
    },
    {
      key: "health",
      header: "Health",
      align: "right",
      hideBelow: "md",
      render: (r) => (
        <span className="mono text-xs text-muted">
          {r.health_score != null ? `${r.health_score}%` : "—"}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Versiones & Releases"
        subtitle="Canales canary/stable, health-gate y diff entre versiones."
      />
      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)] lg:items-start">
          <div className="space-y-4 lg:sticky lg:top-6">
            <Panel>
              <PanelHeader
                title="Nuevo release"
                description="Elegí agente, versión y canal; el tráfico define el porcentaje expuesto."
              />
              <div className="panel-body flex flex-col gap-4">
                <Field label="Agente">
                  <Select
                    value={agentId}
                    onChange={(e) => {
                      setAgentId(e.target.value);
                      setStartForm((f) => ({ ...f, version_id: "" }));
                      void loadVersions(e.target.value);
                    }}
                    placeholder="Elegí un agente"
                  >
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Versión">
                  <Select
                    value={startForm.version_id}
                    onChange={(e) => setStartForm((f) => ({ ...f, version_id: e.target.value }))}
                    placeholder="Elegí una versión"
                  >
                    {versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version_number} ({v.status})
                      </option>
                    ))}
                  </Select>
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Canal">
                    <Select
                      value={startForm.channel}
                      onChange={(e) => setStartForm((f) => ({ ...f, channel: e.target.value }))}
                    >
                      {["canary", "stable"].map((ch) => (
                        <option key={ch} value={ch}>
                          {ch}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Tráfico (%)">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={startForm.traffic_pct}
                      onChange={(e) =>
                        setStartForm((f) => ({ ...f, traffic_pct: Number(e.target.value) }))
                      }
                    />
                  </Field>
                </div>
                <Button
                  variant="primary"
                  leadingIcon={Play}
                  loading={busy === "start"}
                  disabled={!agentId || !startForm.version_id}
                  onClick={() => void start()}
                >
                  Iniciar release
                </Button>
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Diff de versiones"
                description="Compará dos versiones del agente seleccionado."
              />
              <div className="panel-body">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Versión A">
                    <Select
                      value={diffPair.a}
                      onChange={(e) => setDiffPair((p) => ({ ...p, a: e.target.value }))}
                      placeholder="A…"
                    >
                      {versions.map((v) => (
                        <option key={v.id} value={v.id}>
                          v{v.version_number}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Versión B">
                    <Select
                      value={diffPair.b}
                      onChange={(e) => setDiffPair((p) => ({ ...p, b: e.target.value }))}
                      placeholder="B…"
                    >
                      {versions.map((v) => (
                        <option key={v.id} value={v.id}>
                          v{v.version_number}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
                <Button
                  variant="secondary"
                  leadingIcon={GitBranch}
                  className="mt-3"
                  disabled={!diffPair.a || !diffPair.b}
                  onClick={() => void showDiff()}
                >
                  Comparar
                </Button>
                {diff && (
                  <div className="mt-3 rounded-md border border-border bg-control p-3">
                    <p className="flex flex-wrap items-center gap-2 text-[13px] text-text">
                      v{diff.version_a.number} → v{diff.version_b.number}
                      <Badge tone={diff.model_changed ? "warn" : "neutral"}>
                        modelo {diff.model_changed ? "cambió" : "igual"}
                      </Badge>
                      <Badge tone={diff.tools_changed ? "warn" : "neutral"}>
                        tools {diff.tools_changed ? "cambiaron" : "iguales"}
                      </Badge>
                    </p>
                    <div className="mt-2 max-h-56 space-y-1.5 overflow-auto">
                      {diff.config_diff.map((c) => (
                        <p
                          key={c.key}
                          className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted"
                        >
                          <Badge tone={diffTone(c.kind)}>{c.kind}</Badge>
                          <span className="mono text-text">{c.key}</span>
                          <span className="mono">{JSON.stringify(c.a ?? "—")}</span>
                          <span aria-hidden>→</span>
                          <span className="mono">{JSON.stringify(c.b ?? "—")}</span>
                        </p>
                      ))}
                      {diff.prompt_diff.changed && (
                        <p className="text-[11px] text-faint">
                          Prompt: {diff.prompt_diff.a_chars} → {diff.prompt_diff.b_chars} chars
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          </div>

          <DataTable
            columns={columns}
            rows={releases}
            rowKey={(r) => r.id}
            caption="Releases"
            loading={loading}
            empty={
              <EmptyState
                icon={RocketLaunch}
                title="Sin releases"
                body="Iniciá un release para promover una versión con tráfico controlado."
              />
            }
            rowActions={(r) => (
              <span className="flex items-center justify-end gap-1">
                <Button variant="ghost" size="sm" onClick={() => void showDetail(r.id)}>
                  Detalle
                </Button>
                <Menu
                  label={`Acciones de v${r.version_number}`}
                  trigger={
                    <Button variant="secondary" size="sm" trailingIcon={CaretDown}>
                      Acciones
                    </Button>
                  }
                >
                  {RELEASE_ACTIONS.map(({ action, label, icon: ActionIcon }) => (
                    <MenuItem
                      key={action}
                      className={menuItemClass}
                      disabled={!!busy}
                      onSelect={() => void act(r.id, action)}
                    >
                      <ActionIcon size={14} aria-hidden />
                      {label}
                    </MenuItem>
                  ))}
                </Menu>
              </span>
            )}
          />
        </div>
      </div>

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail ? `Release ${detail.id.slice(0, 8)} · v${detail.version_number}` : "Release"}
        description={detail ? `${detail.channel} · ${detail.traffic_pct}% de tráfico` : undefined}
        width={520}
      >
        {detail && (
          <div className="space-y-5">
            <KeyValue
              columns={2}
              items={[
                { key: "Estado", value: <StatusBadge status={detail.status} /> },
                { key: "Canal", value: <Badge tone={detail.channel === "canary" ? "info" : "neutral"}>{detail.channel}</Badge> },
                { key: "Tráfico", value: `${detail.traffic_pct}%`, mono: true },
                {
                  key: "Health",
                  value: detail.health_score != null ? `${detail.health_score}%` : "—",
                  mono: true,
                },
                { key: "Agente", value: detail.agent_id, mono: true },
                { key: "Creado", value: fmtDateTime(detail.created_at) },
              ]}
            />
            <section>
              <p className="eyebrow mb-1">Eventos</p>
              <Timeline
                items={(detail.events ?? []).map(
                  (e): TimelineItem => ({
                    id: e.id,
                    at: e.created_at,
                    title: e.event_type,
                    detail: e.detail,
                    kind: "deployment",
                    tone: e.event_type.includes("fail")
                      ? "danger"
                      : e.event_type === "promoted" || e.event_type === "health_ok"
                        ? "ok"
                        : "default",
                  }),
                )}
              />
            </section>
          </div>
        )}
      </Drawer>
    </div>
  );
}
