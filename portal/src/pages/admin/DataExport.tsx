import { DownloadSimple, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  SectionHeader,
  Select,
  SkeletonTable,
  StatusBadge,
  SuccessInline,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Export = {
  id: string;
  organization_id: string;
  scope: string;
  anonymized: boolean;
  status: string;
  size_bytes: number;
  row_counts: Record<string, number>;
  requested_by: string | null;
  requested_at: string;
  completed_at: string | null;
};

type Policy = {
  id: string;
  organization_id: string | null;
  data_type: string;
  retention_days: number;
  enabled: boolean;
};

type Purge = { id: string; data_type: string; organization_id: string | null; purged_rows: number; ran_at: string };

const fmtBytes = (b: number) =>
  b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)}MB` : `${(b / 1024).toFixed(1)}KB`;

const SCOPE_OPTIONS = ["all", "kb", "agents", "usage", "config"];
const DATA_TYPES = ["usage_events", "inference_logs", "api_logs", "audit_logs", "agent_versions"];

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("es-PE") : "—";
}

export default function AdminDataExportPage() {
  const { session } = usePlatformAuth();
  const [exports, setExports] = useState<Export[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [purges, setPurges] = useState<Purge[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [form, setForm] = useState({ scope: "all", anonymized: false });
  const [policyForm, setPolicyForm] = useState({ data_type: "inference_logs", retention_days: 90, enabled: true });
  const [detailExport, setDetailExport] = useState<Export | null>(null);
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [confirmPolicy, setConfirmPolicy] = useState<Policy | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function loadAll(oid: string) {
    if (!session) return;
    setError("");
    try {
      const [e, p, g] = await Promise.all([
        platformApi<{ exports: Export[] }>(
          `/api/v1/platform/data-export/exports?organization_id=${oid}`,
          { token: session.token }
        ),
        platformApi<{ policies: Policy[] }>("/api/v1/platform/data-export/retention/policies", {
          token: session.token,
        }),
        platformApi<{ purges: Purge[] }>("/api/v1/platform/data-export/retention/purges", {
          token: session.token,
        }),
      ]);
      setExports(e.exports || []);
      setPolicies(p.policies || []);
      setPurges(g.purges || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>(
          "/api/v1/platform/organizations",
          { token: session.token }
        );
        setOrgs(o.organizations || []);
        if (o.organizations?.length) {
          setOrgId(o.organizations[0].id);
          await loadAll(o.organizations[0].id);
        } else {
          await loadAll("");
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createExport() {
    if (!session) return;
    setBusy("export");
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ id: string; size_bytes: number }>(
        "/api/v1/platform/data-export/export",
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ organization_id: orgId, ...form }),
        }
      );
      setNote(`Export ${out.id.slice(0, 8)}… listo (${fmtBytes(out.size_bytes)}).`);
      await loadAll(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function upsertPolicy() {
    if (!session) return;
    setBusy("policy");
    setError("");
    setNote("");
    try {
      await platformApi("/api/v1/platform/data-export/retention/policies", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(policyForm),
      });
      setNote(`Política de ${policyForm.data_type} guardada.`);
      await loadAll(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function removePolicy(id: string) {
    if (!session) return;
    setBusy(`del-${id}`);
    setError("");
    setNote("");
    try {
      await platformApi(`/api/v1/platform/data-export/retention/policies/${id}`, {
        method: "DELETE",
        token: session.token,
      });
      setConfirmPolicy(null);
      setNote("Política eliminada.");
      await loadAll(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function purgeNow() {
    if (!session) return;
    setBusy("purge");
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ purged: Purge[] }>("/api/v1/platform/data-export/retention/purge", {
        method: "POST",
        token: session.token,
      });
      setConfirmPurge(false);
      setNote(`${out.purged.length} tabla(s) purgada(s).`);
      await loadAll(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  function download(e: Export) {
    if (!session) return;
    window.open(
      `/api/v1/platform/data-export/exports/${e.id}/download?token=${encodeURIComponent(session.token || "")}`,
      "_blank"
    );
  }

  const anonymized = exports.filter((e) => e.anonymized).length;
  const anonPct = exports.length ? (anonymized / exports.length) * 100 : 0;
  const latest = exports.reduce<Export | null>(
    (acc, e) => (!acc || new Date(e.requested_at) > new Date(acc.requested_at) ? e : acc),
    null
  );
  const activePolicies = policies.filter((p) => p.enabled).length;
  const purgedRows = purges.reduce((sum, p) => sum + p.purged_rows, 0);
  const lastPurge = purges.reduce<Purge | null>(
    (acc, p) => (!acc || new Date(p.ran_at) > new Date(acc.ran_at) ? p : acc),
    null
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Export & Compliance"
        subtitle="Export ZIP con anonimización, auditoría de exportaciones y retención granular."
      />
      <ErrorInline message={error} />
      {note && <SuccessInline>{note}</SuccessInline>}
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={6} />
        </Panel>
      ) : (
        <>
          <Panel className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Exportaciones auditadas</p>
                <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
                  {exports.length.toLocaleString()}
                </p>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                  {latest
                    ? `Última: ${formatDateTime(latest.requested_at)} · scope ${latest.scope} · ${fmtBytes(latest.size_bytes)}.`
                    : "Todavía no se exportaron datos para esta organización."}
                </p>
              </div>
              <div className="min-w-[220px] flex-1 sm:max-w-sm">
                {exports.length > 0 ? (
                  <Progress
                    value={anonPct}
                    label="Exportaciones con anonimización"
                    showValue
                  />
                ) : (
                  <p className="text-xs text-faint">Sin exportaciones para medir la proporción.</p>
                )}
              </div>
            </div>
          </Panel>

          <MetricGrid cols={4}>
            <Metric
              size="md"
              label="Anonimizadas"
              value={anonymized.toLocaleString()}
              hint={`de ${exports.length.toLocaleString()} exportaciones`}
            />
            <Metric
              size="md"
              label="Políticas activas"
              value={activePolicies.toLocaleString()}
              hint={`${policies.length} registradas`}
            />
            <Metric size="md" label="Purgas registradas" value={purges.length.toLocaleString()} />
            <Metric
              size="md"
              label="Filas purgadas"
              value={purgedRows.toLocaleString()}
              hint={lastPurge ? `Última ${formatDateTime(lastPurge.ran_at)}` : "Sin purgas ejecutadas"}
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Exportaciones"
              description="Historial auditable. Cada fila abre el detalle con el conteo por tabla."
              className="mb-3"
            />
            <Panel>
              <PanelHeader
                title="Nueva exportación"
                description="Se descarga como ZIP; la anonimización elimina datos personales."
                actions={
                  <Button
                    variant="primary"
                    leadingIcon={DownloadSimple}
                    loading={busy === "export"}
                    disabled={!orgId}
                    onClick={() => void createExport()}
                  >
                    Exportar ZIP
                  </Button>
                }
              />
              <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 lg:items-end">
                <Field label="Organización">
                  <Select
                    value={orgId}
                    placeholder="Organización…"
                    onChange={(e) => {
                      setOrgId(e.target.value);
                      void loadAll(e.target.value);
                    }}
                  >
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id.slice(0, 8)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Scope">
                  <Select
                    value={form.scope}
                    onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))}
                  >
                    {SCOPE_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Checkbox
                  label="Anonimizar"
                  hint="El ZIP se genera sin datos personales."
                  checked={form.anonymized}
                  onCheckedChange={(checked) => setForm((f) => ({ ...f, anonymized: checked }))}
                  className="pb-2"
                />
              </div>
              <div className="overflow-x-auto border-t border-border">
                {exports.length === 0 ? (
                  <EmptyState
                    icon={DownloadSimple}
                    compact
                    title="Sin exportaciones"
                    body="No se registraron exportaciones para esta organización."
                    hint="Generá la primera con el formulario de arriba."
                  />
                ) : (
                  <table className="table min-w-[960px]">
                    <thead>
                      <tr>
                        <th>Fecha</th>
                        <th>Scope</th>
                        <th>Anon.</th>
                        <th>Filas</th>
                        <th className="text-right">Tamaño</th>
                        <th>Solicitado por</th>
                        <th>Estado</th>
                        <th className="text-right">Descarga</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exports.map((e) => (
                        <tr key={e.id} className="cursor-pointer" onClick={() => setDetailExport(e)}>
                          <td className="text-xs text-muted tabular-nums">
                            {formatDateTime(e.requested_at)}
                          </td>
                          <td className="text-xs text-muted">{e.scope}</td>
                          <td>
                            <Badge tone={e.anonymized ? "ok" : "neutral"} dot>
                              {e.anonymized ? "Sí" : "No"}
                            </Badge>
                          </td>
                          <td className="mono max-w-64 truncate text-[11px] text-faint">
                            {Object.entries(e.row_counts)
                              .map(([k, v]) => `${k}:${v}`)
                              .join(" · ") || "—"}
                          </td>
                          <td className="text-right tabular-nums">{fmtBytes(e.size_bytes)}</td>
                          <td className="mono text-xs text-faint">{e.requested_by?.slice(0, 8) ?? "—"}</td>
                          <td>
                            <StatusBadge status={e.status} />
                          </td>
                          <td className="text-right">
                            <IconButton
                              label={`Descargar export ${e.id.slice(0, 8)}`}
                              icon={DownloadSimple}
                              onClick={(ev) => {
                                ev.stopPropagation();
                                download(e);
                              }}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Panel>
          </section>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <SectionHeader
                title="Retención granular"
                description="Cada política define cuántos días se conserva un tipo de dato."
                className="mb-3"
              />
              <Panel>
                <div className="space-y-3 p-4">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <Field label="Tipo de dato">
                      <Select
                        value={policyForm.data_type}
                        onChange={(e) => setPolicyForm((f) => ({ ...f, data_type: e.target.value }))}
                      >
                        {DATA_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="Días de retención">
                      <Input
                        type="number"
                        min={0}
                        value={policyForm.retention_days}
                        onChange={(e) =>
                          setPolicyForm((f) => ({ ...f, retention_days: Number(e.target.value) }))
                        }
                      />
                    </Field>
                  </div>
                  <Checkbox
                    label="Política activa"
                    hint="Si la desactivás, la purga la ignora."
                    checked={policyForm.enabled}
                    onCheckedChange={(checked) => setPolicyForm((f) => ({ ...f, enabled: checked }))}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="primary" loading={busy === "policy"} onClick={() => void upsertPolicy()}>
                      Guardar política
                    </Button>
                    <Button
                      variant="danger"
                      leadingIcon={Trash}
                      loading={busy === "purge"}
                      disabled={activePolicies === 0}
                      onClick={() => setConfirmPurge(true)}
                    >
                      Purgar ahora
                    </Button>
                  </div>
                  <p className="text-xs text-faint">
                    La purga aplica {activePolicies} política(s) activa(s) y reporta las tablas afectadas.
                  </p>
                </div>
                <div className="border-t border-border">
                  {policies.length === 0 ? (
                    <EmptyState
                      icon={Trash}
                      compact
                      title="Sin políticas de retención"
                      body="Ningún tipo de dato tiene retención configurada."
                    />
                  ) : (
                    <ul className="divide-y divide-border-soft">
                      {policies.map((p) => (
                        <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
                          <span className="mono text-xs text-text">{p.data_type}</span>
                          <span className="text-xs text-faint tabular-nums">{p.retention_days}d</span>
                          <Badge tone="neutral">{p.organization_id ? "org" : "global"}</Badge>
                          <Badge tone={p.enabled ? "ok" : "neutral"} dot>
                            {p.enabled ? "Activa" : "Inactiva"}
                          </Badge>
                          <IconButton
                            label={`Eliminar política de ${p.data_type}`}
                            icon={Trash}
                            variant="ghost"
                            iconSize={14}
                            loading={busy === `del-${p.id}`}
                            onClick={() => setConfirmPolicy(p)}
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Panel>
            </section>

            <section>
              <SectionHeader
                title="Historial de purgas"
                description="Cada ejecución de retención queda auditada con las filas eliminadas."
                className="mb-3"
              />
              <Panel className="overflow-x-auto">
                {purges.length === 0 ? (
                  <EmptyState
                    icon={Trash}
                    compact
                    title="Sin purgas"
                    body="Todavía no se ejecutó ninguna purga de retención."
                  />
                ) : (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Hora</th>
                        <th>Tabla</th>
                        <th>Origen</th>
                        <th className="text-right">Filas purgadas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {purges.map((g) => (
                        <tr key={g.id}>
                          <td className="text-xs text-muted tabular-nums">{formatDateTime(g.ran_at)}</td>
                          <td className="mono text-xs">{g.data_type}</td>
                          <td className="mono text-[11px] text-faint">
                            {g.organization_id?.slice(0, 8) ?? "global"}
                          </td>
                          <td className="text-right tabular-nums">{g.purged_rows.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Panel>
            </section>
          </div>
        </>
      )}

      <Drawer
        open={detailExport !== null}
        onOpenChange={(open) => !open && setDetailExport(null)}
        title={detailExport ? `Export ${detailExport.scope}` : "Exportación"}
        description={detailExport ? `ID ${detailExport.id}` : undefined}
        footer={
          detailExport ? (
            <>
              <Button variant="secondary" onClick={() => setDetailExport(null)}>
                Cerrar
              </Button>
              <Button variant="primary" leadingIcon={DownloadSimple} onClick={() => download(detailExport)}>
                Descargar ZIP
              </Button>
            </>
          ) : undefined
        }
      >
        {detailExport && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={detailExport.status} />
              <Badge tone={detailExport.anonymized ? "ok" : "neutral"} dot>
                {detailExport.anonymized ? "Anonimizado" : "Sin anonimizar"}
              </Badge>
              <Badge tone="neutral">{fmtBytes(detailExport.size_bytes)}</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Solicitado", value: formatDateTime(detailExport.requested_at), mono: true },
                { key: "Completado", value: formatDateTime(detailExport.completed_at), mono: true },
                { key: "Solicitado por", value: detailExport.requested_by ?? "—", mono: true },
                { key: "Organización", value: detailExport.organization_id, mono: true },
              ]}
            />
            <div>
              <h3 className="eyebrow mb-2">Conteo por tabla</h3>
              {Object.keys(detailExport.row_counts ?? {}).length === 0 ? (
                <p className="text-[13px] text-muted">El export no reportó conteos por tabla.</p>
              ) : (
                <ul className="divide-y divide-border-soft rounded-md border border-border">
                  {Object.entries(detailExport.row_counts).map(([table, rows]) => (
                    <li key={table} className="flex items-center justify-between gap-3 px-3 py-2">
                      <span className="mono text-xs text-muted">{table}</span>
                      <span className="tabular-nums text-text">{rows.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmPurge}
        onOpenChange={setConfirmPurge}
        title="Purgar datos ahora"
        body={`Se aplican ${activePolicies} política(s) activa(s) y se eliminan los datos vencidos. La acción no se puede deshacer.`}
        confirmLabel="Purgar ahora"
        tone="danger"
        loading={busy === "purge"}
        onConfirm={() => void purgeNow()}
      />

      <ConfirmDialog
        open={confirmPolicy !== null}
        onOpenChange={(open) => !open && setConfirmPolicy(null)}
        title="Eliminar política de retención"
        body={
          confirmPolicy
            ? `La política de ${confirmPolicy.data_type} deja de aplicarse. Los datos existentes no se borran hasta la próxima purga.`
            : undefined
        }
        confirmLabel="Eliminar"
        tone="danger"
        loading={confirmPolicy !== null && busy === `del-${confirmPolicy.id}`}
        onConfirm={() => confirmPolicy && void removePolicy(confirmPolicy.id)}
      />
    </div>
  );
}
