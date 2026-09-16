import {
  CheckCircle,
  Crosshair,
  Info,
  Minus,
  Prohibit,
  Question,
  ShieldCheck,
  ShieldWarning,
  WarningCircle,
  WarningOctagon,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  InfoInline,
  KeyValue,
  Menu,
  MenuItem,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  SkeletonBlock,
  SuccessInline,
  WarningInline,
  menuItemClass,
  menuLabelClass,
  MenuLabel,
  type Column,
  type SortState,
  type Tone,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Ev = { id: string; event_type: string; severity: string; score: number; status: string; evidence: Record<string, unknown>; responses: number; detected_at: string; resolved_at: string | null; timeline?: { step: string; detail: string; at: string }[] };
type Detail = Ev & { responses: { id: string; action_type: string; target: string; status: string; detail: string; created_at: string }[] };
type Posture = { threat_score: number; open_events: number; by_type: { event_type: string; count: number; avg_score: number }[] };
type Trend = { trend: { date: string; threat_score: number; open_events: number }[] };

/**
 * Escala única de severidad del bloque de seguridad y riesgo
 * (crítica → alta → media → baja). Mismos valores en SecurityAudit,
 * SecurityCenter y RiskCenter.
 */
const SEVERITY_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  critical: { label: "Crítica", tone: "danger", icon: WarningOctagon },
  high: { label: "Alta", tone: "warn", icon: WarningCircle },
  medium: { label: "Media", tone: "info", icon: Info },
  low: { label: "Baja", tone: "neutral", icon: Minus },
  info: { label: "Informativa", tone: "neutral", icon: Info },
};

function SeverityBadge({ severity }: { severity: string }) {
  const meta = SEVERITY_META[severity] ?? {
    label: severity || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

/**
 * Estados de eventos SOC: no están en STATUS_META (components/ui/Badge.tsx,
 * fuera del alcance de esta fase). Mismos valores en SecurityAudit.
 */
const SOC_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  detected: { label: "Detectado", tone: "danger", icon: WarningOctagon },
  contained: { label: "Contenido", tone: "warn", icon: ShieldWarning },
  resolved: { label: "Resuelto", tone: "ok", icon: CheckCircle },
  false_positive: { label: "Falso positivo", tone: "neutral", icon: Prohibit },
};

function SocStatusBadge({ status }: { status: string }) {
  const meta = SOC_STATUS_META[status] ?? {
    label: status || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

/** Respuestas disponibles ante un evento. Las destructivas piden confirmación. */
const RESPONSES: { id: string; label: string; irreversible: boolean; body?: string }[] = [
  {
    id: "revoke_key",
    label: "Revocar clave comprometida",
    irreversible: true,
    body: "Las claves vinculadas al evento dejan de funcionar de inmediato. La acción queda auditada y no se puede deshacer.",
  },
  {
    id: "block_deployment",
    label: "Bloquear despliegue",
    irreversible: true,
    body: "El despliegue vinculado queda bloqueado hasta que se levante la medida de forma manual.",
  },
  { id: "throttle", label: "Limitar tráfico", irreversible: false },
  { id: "alert", label: "Notificar al equipo", irreversible: false },
];

const EVENT_COLUMNS: Column<Ev>[] = [
  {
    key: "event_type",
    header: "Evento",
    sortable: true,
    render: (e) => <span className="mono text-xs text-text">{e.event_type}</span>,
  },
  {
    key: "severity",
    header: "Severidad",
    sortable: true,
    render: (e) => <SeverityBadge severity={e.severity} />,
  },
  {
    key: "score",
    header: "Score",
    sortable: true,
    align: "right",
    render: (e) => <span className="mono text-xs text-muted">{Math.round(e.score)}</span>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (e) => <SocStatusBadge status={e.status} />,
  },
  {
    key: "detected_at",
    header: "Detectado",
    sortable: true,
    hideBelow: "md",
    render: (e) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(e.detected_at)}</span>,
  },
];

const PAGE_SIZE = 15;

export default function SecurityCenterPage() {
  const { session } = useAuth();
  const [events, setEvents] = useState<Ev[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ tone: "ok" | "warn" | "info"; text: string } | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "detected_at", dir: "desc" });
  const [severityFilter, setSeverityFilter] = useState("");
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState<{ kind: "resolve" } | { kind: "respond"; action: string } | null>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [e, p, t] = await Promise.all([
        api<{ events: Ev[] }>("/api/v1/soc/events", { token: session.token, organizationId: session.organizationId }),
        api<Posture>("/api/v1/soc/posture", { token: session.token, organizationId: session.organizationId }),
        api<Trend>("/api/v1/soc/posture/trend", { token: session.token, organizationId: session.organizationId }),
      ]);
      setEvents(e.events || []);
      setPosture(p);
      setTrend(t);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function scan() {
    if (!session) return;
    setBusy("scan");
    setError("");
    setNotice(null);
    try {
      const out = await api<{ detected: { event_type: string; severity: string }[] }>("/api/v1/soc/scan", { method: "POST", token: session.token, organizationId: session.organizationId });
      setNotice(
        out.detected.length
          ? {
              tone: "warn",
              text: `Detecciones nuevas: ${out.detected.map((d) => `${d.event_type} (${SEVERITY_META[d.severity]?.label ?? d.severity})`).join(", ")}`,
            }
          : { tone: "ok", text: "Escaneo sin amenazas nuevas." },
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(eventId: string, action: string) {
    if (!session) return;
    setBusy(`${action}-${eventId.slice(0, 6)}`);
    setError("");
    try {
      const body = action === "resolve" ? JSON.stringify({ verdict: "resolved" }) : JSON.stringify({ action_type: action });
      const url = action === "resolve" ? `/api/v1/soc/events/${eventId}/resolve` : `/api/v1/soc/events/${eventId}/respond`;
      await api(url, { method: "POST", token: session.token, organizationId: session.organizationId, body });
      const label = action === "resolve" ? "Evento resuelto" : RESPONSES.find((r) => r.id === action)?.label ?? action;
      setNotice({ tone: "ok", text: `${label}. Queda registrado en la respuesta del evento.` });
      await load();
      if (detail?.id === eventId) await showDetail(eventId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(eventId: string) {
    if (!session) return;
    setDetailLoading(true);
    try {
      const d = await api<Detail>(`/api/v1/soc/events/${eventId}`, { token: session.token, organizationId: session.organizationId });
      setDetail(d);
    } finally {
      setDetailLoading(false);
    }
  }

  const severities = useMemo(() => Array.from(new Set(events.map((e) => e.severity))).sort(), [events]);

  const rows = useMemo(() => {
    const filtered = severityFilter ? events.filter((e) => e.severity === severityFilter) : events;
    if (!sort) return filtered;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const left = (a as unknown as Record<string, unknown>)[sort.key];
      const right = (b as unknown as Record<string, unknown>)[sort.key];
      if (typeof left === "number" && typeof right === "number") return (left - right) * dir;
      return String(left ?? "").localeCompare(String(right ?? ""), "es") * dir;
    });
  }, [events, severityFilter, sort]);

  const visible = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const trendPoints = (trend?.trend ?? []).slice(-14);
  const trendMax = Math.max(1, ...trendPoints.map((t) => t.threat_score));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Security Operations Center"
        subtitle="Detección de amenazas, respuesta registrada y postura de seguridad del workspace."
        actions={
          <Button variant="primary" leadingIcon={Crosshair} loading={busy === "scan"} disabled={busy !== ""} onClick={() => void scan()}>
            Escanear ahora
          </Button>
        }
      />

      {error && <ErrorInline>{error}</ErrorInline>}
      {notice &&
        (notice.tone === "ok" ? (
          <SuccessInline message={notice.text} />
        ) : notice.tone === "warn" ? (
          <WarningInline message={notice.text} />
        ) : (
          <InfoInline message={notice.text} />
        ))}

      {loading ? (
        <div className="panel">
          <div className="panel-body">
            <SkeletonBlock rows={6} />
          </div>
        </div>
      ) : (
        <>
          <MetricGrid>
            <Metric
              label="Threat score"
              value={posture?.threat_score ?? 0}
              hint={`${posture?.open_events ?? 0} eventos abiertos`}
              help="Puntaje agregado de la postura: sube con eventos abiertos y su severidad."
            />
            <Metric label="Eventos registrados" value={events.length} size="md" hint="En la ventana de detección" />
            <Metric label="Eventos abiertos" value={posture?.open_events ?? 0} size="md" tone={(posture?.open_events ?? 0) > 0 ? "warn" : "default"} />
            <Metric label="Tipos con hallazgos" value={posture?.by_type.length ?? 0} size="md" />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="lg:col-span-2">
              <DataTable
                columns={EVENT_COLUMNS}
                rows={visible}
                rowKey={(e) => e.id}
                caption="Eventos de seguridad detectados"
                stickyHeader
                sort={sort}
                onSortChange={(next) => {
                  setSort(next);
                  setPage(1);
                }}
                onRowClick={(e) => void showDetail(e.id)}
                toolbar={
                  <>
                    <p className="text-xs text-muted">Se actualiza cada 15 segundos.</p>
                    <span className="flex-1" aria-hidden />
                    {severities.length > 1 && (
                      <Select
                        className="w-full sm:w-52"
                        aria-label="Filtrar por severidad"
                        placeholder="Todas las severidades"
                        value={severityFilter}
                        onChange={(e) => {
                          setSeverityFilter(e.target.value);
                          setPage(1);
                        }}
                      >
                        {severities.map((s) => (
                          <option key={s} value={s}>
                            {SEVERITY_META[s]?.label ?? s}
                          </option>
                        ))}
                      </Select>
                    )}
                  </>
                }
                empty={
                  <EmptyState
                    icon={ShieldCheck}
                    title={events.length === 0 ? "Sin eventos detectados" : "Sin coincidencias"}
                    body={
                      events.length === 0
                        ? "El motor no encontró inyecciones, fugas de PII, abuso de claves ni picos de tráfico en esta organización."
                        : "Ningún evento coincide con la severidad seleccionada."
                    }
                    hint={events.length === 0 ? "Corré un escaneo para revisar la ventana actual." : undefined}
                    action={
                      events.length === 0 ? (
                        <Button variant="secondary" leadingIcon={Crosshair} loading={busy === "scan"} onClick={() => void scan()}>
                          Escanear ahora
                        </Button>
                      ) : undefined
                    }
                  />
                }
                footer={
                  rows.length > 0 ? (
                    <>
                      <ResultCount shown={visible.length} total={rows.length} noun="eventos" />
                      {rows.length > PAGE_SIZE && (
                        <Pagination page={page} pageSize={PAGE_SIZE} total={rows.length} onPageChange={setPage} />
                      )}
                    </>
                  ) : undefined
                }
              />
            </div>

            <div className="space-y-4">
              <Panel>
                <PanelHeader
                  title="Postura por tipo"
                  description="Volumen y score medio de los eventos agrupados por tipo."
                />
                <div className="panel-body">
                  {(posture?.by_type ?? []).length === 0 ? (
                    <p className="text-[13px] leading-relaxed text-muted">
                      Todavía no hay eventos agrupados: la postura se completa cuando el motor registra detecciones.
                    </p>
                  ) : (
                    <ul className="divide-y divide-border-soft">
                      {(posture?.by_type ?? []).map((t) => (
                        <li key={t.event_type} className="flex items-baseline justify-between gap-3 py-2 first:pt-0 last:pb-0">
                          <span className="mono min-w-0 truncate text-xs text-text">{t.event_type}</span>
                          <span className="shrink-0 text-xs text-muted tabular-nums">
                            {t.count} · score {Math.round(t.avg_score)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Panel>

              <Panel>
                <PanelHeader title="Tendencia" description="Threat score de los últimos 14 días con datos." />
                <div className="panel-body">
                  {trendPoints.length === 0 ? (
                    <p className="text-[13px] leading-relaxed text-muted">Sin serie histórica todavía.</p>
                  ) : (
                    <>
                      <div className="flex h-20 items-end gap-1" aria-hidden>
                        {trendPoints.map((t) => (
                          <div
                            key={t.date}
                            className="flex-1 rounded-t-xs bg-danger/60 transition-colors duration-150 hover:bg-danger"
                            style={{ height: `${Math.max((t.threat_score / trendMax) * 100, 3)}%` }}
                            title={`${t.date}: ${t.threat_score}`}
                          />
                        ))}
                      </div>
                      <p className="mt-2 text-xs text-faint tabular-nums">
                        {trendPoints[0].date} — {trendPoints[trendPoints.length - 1].date} · máximo {trendMax}
                      </p>
                    </>
                  )}
                </div>
              </Panel>

              <Panel>
                <PanelHeader title="Qué monitorea" />
                <div className="panel-body">
                  <ul className="flex flex-col gap-2 text-[13px] leading-relaxed text-muted">
                    <li>Inyección de instrucciones en mensajes del copilot.</li>
                    <li>Salidas bloqueadas por PII o intento de exfiltración.</li>
                    <li>Fallos de autenticación y abuso de API keys.</li>
                    <li>Picos de tráfico anómalos.</li>
                  </ul>
                  <p className="mt-3 text-xs leading-relaxed text-faint">
                    Los eventos con score alto se deduplican por 24 h para no repetir el mismo hallazgo.
                  </p>
                </div>
              </Panel>
            </div>
          </div>
        </>
      )}

      <Drawer
        open={Boolean(detail)}
        onOpenChange={(open) => !open && setDetail(null)}
        title="Detalle del evento"
        description={detail?.event_type}
        width={520}
        footer={
          detail && (
            <>
              <Menu
                label="Respuestas disponibles"
                align="end"
                side="top"
                trigger={
                  <Button variant="secondary" leadingIcon={ShieldWarning} disabled={!!busy}>
                    Responder
                  </Button>
                }
              >
                <MenuLabel className={menuLabelClass}>Respuesta registrada</MenuLabel>
                {RESPONSES.map((r) => (
                  <MenuItem
                    key={r.id}
                    className={menuItemClass}
                    disabled={!!busy}
                    onSelect={() => setConfirm({ kind: "respond", action: r.id })}
                  >
                    {r.label}
                  </MenuItem>
                ))}
              </Menu>
              <Button
                variant="primary"
                leadingIcon={ShieldCheck}
                disabled={!!busy || detail.status === "resolved"}
                onClick={() => setConfirm({ kind: "resolve" })}
              >
                Resolver
              </Button>
            </>
          )
        }
      >
        {detailLoading && !detail ? (
          <SkeletonBlock rows={5} />
        ) : detail ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={detail.severity} />
              <SocStatusBadge status={detail.status} />
              <Badge tone="neutral">Score {Math.round(detail.score)}</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Detectado", value: fmtDateTime(detail.detected_at) },
                { key: "Resuelto", value: detail.resolved_at ? fmtDateTime(detail.resolved_at) : "Sin resolver" },
              ]}
            />

            <div>
              <p className="eyebrow mb-2">Línea de tiempo</p>
              {(detail.timeline ?? []).length === 0 ? (
                <p className="text-[13px] text-muted">El evento no tiene pasos registrados.</p>
              ) : (
                <ol className="relative ml-2 border-l border-border-soft">
                  {(detail.timeline ?? []).map((tl) => (
                    <li key={`${tl.step}-${tl.at}`} className="relative ml-4 pb-3 pl-3 last:pb-0">
                      <span className="absolute top-1.5 -left-[5px] h-2 w-2 rounded-full bg-accent" aria-hidden />
                      <p className="text-[13px] font-medium text-text">{tl.step}</p>
                      <p className="text-xs leading-relaxed text-muted">{tl.detail}</p>
                      <p className="mt-0.5 text-[11px] text-faint tabular-nums">{fmtDateTime(tl.at)}</p>
                    </li>
                  ))}
                </ol>
              )}
            </div>

            <div>
              <p className="eyebrow mb-2">Respuestas ({detail.responses.length})</p>
              {detail.responses.length === 0 ? (
                <p className="text-[13px] leading-relaxed text-muted">
                  Sin respuestas registradas. Las acciones que ejecutes desde este panel quedan acá.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {detail.responses.map((r) => (
                    <li key={r.id} className="rounded-sm border border-border-soft bg-raised px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="mono text-xs text-text">{r.action_type}</span>
                        <Badge tone="neutral">{r.target}</Badge>
                        <span className="ml-auto text-[11px] text-faint tabular-nums">{fmtDateTime(r.created_at)}</span>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted">{r.detail}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <p className="eyebrow mb-2">Evidencia</p>
              <CodeBlock code={JSON.stringify(detail.evidence, null, 2)} language="json" maxHeight={240} />
            </div>
          </div>
        ) : null}
      </Drawer>

      <ConfirmDialog
        open={confirm?.kind === "resolve"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Resolver evento"
        body="Se registra el veredicto resuelto y el evento sale de los abiertos. La decisión queda auditada."
        confirmLabel="Resolver"
        tone="primary"
        loading={busy === `resolve-${detail?.id.slice(0, 6)}`}
        onConfirm={() => {
          if (detail) void act(detail.id, "resolve");
          setConfirm(null);
        }}
      />

      <ConfirmDialog
        open={confirm?.kind === "respond"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={RESPONSES.find((r) => r.id === (confirm?.kind === "respond" ? confirm.action : ""))?.label ?? "Responder"}
        body={
          RESPONSES.find((r) => r.id === (confirm?.kind === "respond" ? confirm.action : ""))?.body ??
          "La respuesta queda registrada en la auditoría del evento."
        }
        confirmLabel="Ejecutar respuesta"
        tone="danger"
        onConfirm={() => {
          if (detail && confirm?.kind === "respond") void act(detail.id, confirm.action);
          setConfirm(null);
        }}
      />
    </div>
  );
}
