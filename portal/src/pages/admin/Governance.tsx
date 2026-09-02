import { Key, Scroll, ShieldCheck, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type GovProfile = {
  organization_id: string;
  retention_days: number;
  data_residency_region: string | null;
  dsr_contact_email: string | null;
};

type ComplianceEvent = {
  id: string;
  organization_id: string;
  event_type: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

type KmsKey = {
  id: string;
  name: string;
  key_version: number;
  status: string;
  created_at: string;
  retired_at: string | null;
};

export default function AdminGovernancePage() {
  const { session } = usePlatformAuth();
  const [profiles, setProfiles] = useState<GovProfile[]>([]);
  const [events, setEvents] = useState<ComplianceEvent[]>([]);
  const [kmsKeys, setKmsKeys] = useState<KmsKey[]>([]);
  const [kmsStatus, setKmsStatus] = useState<{ keys: number; active_version: number | null } | null>(null);
  const [regions, setRegions] = useState<{ code: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Record<string, GovProfile>>({});

  async function load() {
    if (!session) return;
    setError("");
    try {
      const orgs = await platformApi<{ organizations: { id: string }[] }>(
        "/api/v1/platform/organizations",
        { token: session.token }
      );
      const profiles = await Promise.all(
        orgs.organizations.map(async (o) =>
          platformApi<GovProfile>(`/api/v1/platform/governance/organizations/${o.id}`, {
            token: session.token,
          })
        )
      );
      const [ev, kk, ks, rg] = await Promise.all([
        platformApi<{ events: ComplianceEvent[] }>("/api/v1/platform/governance/compliance-events", {
          token: session.token,
        }),
        platformApi<{ keys: KmsKey[] }>("/api/v1/platform/governance/kms/keys", {
          token: session.token,
        }),
        platformApi<{ keys: number; active_version: number | null }>(
          "/api/v1/platform/governance/kms/status",
          { token: session.token }
        ),
        platformApi<{ regions: { code: string; name: string }[] }>(
          "/api/v1/platform/governance/regions",
          { token: session.token }
        ),
      ]);
      setProfiles(profiles);
      setEvents(ev.events || []);
      setKmsKeys(kk.keys || []);
      setKmsStatus(ks);
      setRegions(rg.regions || []);
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

  async function saveProfile(oid: string) {
    if (!session) return;
    setBusy(oid);
    setError("");
    const draft = editing[oid] ?? profiles.find((p) => p.organization_id === oid);
    try {
      await platformApi(`/api/v1/platform/governance/organizations/${oid}`, {
        method: "PUT",
        token: session.token,
        body: JSON.stringify({
          retention_days: draft.retention_days,
          data_residency_region: draft.data_residency_region,
          dsr_contact_email: draft.dsr_contact_email,
        }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function runPurge(dryRun: boolean) {
    if (!session) return;
    setBusy(`purge-${dryRun}`);
    setError("");
    try {
      const out = await platformApi<{ organizations: { organization_id: string; expired: Record<string, number> }[] }>(
        "/api/v1/platform/governance/purge",
        { method: "POST", token: session.token, body: JSON.stringify({ dry_run: dryRun }) }
      );
      const total = out.organizations.reduce(
        (acc, o) => acc + Object.values(o.expired).reduce((a, b) => a + b, 0),
        0
      );
      setError(
        dryRun
          ? `Dry-run: ${total} registros expirados por retención.`
          : `Purge ejecutado: ${total} registros eliminados.`
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function dsr(oid: string, type: "export" | "erasure") {
    if (!session) return;
    if (type === "erasure" && !window.confirm("¿Borrar TODOS los datos personales de este tenant? Es irreversible.")) return;
    setBusy(`${type}-${oid}`);
    setError("");
    try {
      const out = await platformApi<Record<string, unknown>>(
        `/api/v1/platform/governance/organizations/${oid}/dsr-${type}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`${type === "export" ? "Exportación" : "Erase"} OK: ${JSON.stringify(out)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function rotateKms() {
    if (!session) return;
    setBusy("kms-rotate");
    setError("");
    try {
      const out = await platformApi<{ key_version: number }>("/api/v1/platform/governance/kms/keys/any/rotate", {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      setError(`KMS rotado: ahora en versión ${out.key_version}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Governance & Data Residency"
        subtitle="Retención por tenant, residencia de datos, DSR (GDPR) y KMS."
        actions={
          <div className="flex gap-2">
            <button type="button" className="btn btn-secondary min-h-11" disabled={!!busy} onClick={() => void runPurge(true)}>
              Dry-run retención
            </button>
            <button type="button" className="btn btn-primary min-h-11" disabled={!!busy} onClick={() => void runPurge(false)}>
              Aplicar retención
            </button>
          </div>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <ShieldCheck size={15} aria-hidden /> Perfiles por tenant
            </h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Tenant</th>
                    <th>Retención (días)</th>
                    <th>Residencia</th>
                    <th>Contacto DSR</th>
                    <th className="text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((p) => {
                    const draft = editing[p.organization_id] ?? p;
                    return (
                      <tr key={p.organization_id}>
                        <td className="mono text-xs text-faint">{p.organization_id.slice(0, 13)}…</td>
                        <td>
                          <input
                            type="number"
                            min={1}
                            max={3650}
                            className="w-24 rounded-md border border-border bg-soft px-2 py-1.5 text-sm text-text"
                            value={draft.retention_days}
                            onChange={(e) =>
                              setEditing((prev) => ({
                                ...prev,
                                [p.organization_id]: { ...draft, retention_days: Number(e.target.value) },
                              }))
                            }
                          />
                        </td>
                        <td>
                          <select
                            className="rounded-md border border-border bg-soft px-2 py-1.5 text-sm text-text"
                            value={draft.data_residency_region ?? ""}
                            onChange={(e) =>
                              setEditing((prev) => ({
                                ...prev,
                                [p.organization_id]: { ...draft, data_residency_region: e.target.value || null },
                              }))
                            }
                          >
                            <option value="">— sin pin —</option>
                            {regions.map((r) => (
                              <option key={r.code} value={r.code}>
                                {r.code} · {r.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <input
                            type="email"
                            className="w-48 rounded-md border border-border bg-soft px-2 py-1.5 text-sm text-text"
                            placeholder="dsr@tenant.com"
                            value={draft.dsr_contact_email ?? ""}
                            onChange={(e) =>
                              setEditing((prev) => ({
                                ...prev,
                                [p.organization_id]: { ...draft, dsr_contact_email: e.target.value || null },
                              }))
                            }
                          />
                        </td>
                        <td className="text-right">
                          <div className="flex justify-end gap-1">
                            <button
                              type="button"
                              className="btn btn-ghost min-h-9 px-2 py-1.5 text-xs"
                              disabled={!!busy}
                              onClick={() => void saveProfile(p.organization_id)}
                            >
                              Guardar
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost min-h-9 px-2 py-1.5 text-xs"
                              disabled={!!busy}
                              title="Exportar datos personales (cifrado KMS)"
                              onClick={() => void dsr(p.organization_id, "export")}
                            >
                              <Scroll size={13} aria-hidden /> Export
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost min-h-9 px-2 py-1.5 text-xs text-danger"
                              disabled={!!busy}
                              title="Borrar datos personales (irreversible)"
                              onClick={() => void dsr(p.organization_id, "erasure")}
                            >
                              <Trash size={13} aria-hidden /> Erase
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Key size={15} aria-hidden /> KMS (envelope encryption)
            </h3>
            <div className="panel flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="flex items-center gap-4">
                <span className="badge badge-ok">
                  {kmsStatus?.keys ?? 0} claves · versión activa {kmsStatus?.active_version ?? "—"}
                </span>
                <span className="text-xs text-faint">
                  KEK derivada de CONNECTOR_SECRETS_KEY · DEK por versión cifrado en reposo
                </span>
              </div>
              <button
                type="button"
                className="btn btn-secondary min-h-9 text-xs"
                disabled={!!busy}
                onClick={() => void rotateKms()}
              >
                Rotar clave
              </button>
            </div>
            <div className="panel mt-2 overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Versión</th>
                    <th>Nombre</th>
                    <th>Estado</th>
                    <th>Creada</th>
                  </tr>
                </thead>
                <tbody>
                  {kmsKeys.map((k) => (
                    <tr key={k.id}>
                      <td className="mono">{k.key_version}</td>
                      <td className="text-sm text-text">{k.name}</td>
                      <td>
                        <span className={`badge ${k.status === "active" ? "badge-ok" : "badge-muted"}`}>
                          {k.status}
                        </span>
                      </td>
                      <td className="text-xs text-muted">{new Date(k.created_at).toLocaleString("es-PE")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Eventos de cumplimiento</h3>
            <div className="panel">
              {events.length === 0 ? (
                <EmptyState icon={ShieldCheck} title="Sin eventos" body="Las acciones DSR y de retención quedan registradas aquí." />
              ) : (
                <ul className="space-y-1.5 p-3">
                  {events.map((e) => (
                    <li key={e.id} className="flex items-center justify-between gap-2 rounded-md border border-border p-2 text-sm">
                      <span className="mono text-xs text-text">{e.event_type}</span>
                      <span className="text-xs text-faint">
                        {new Date(e.created_at).toLocaleString("es-PE")} · {JSON.stringify(e.metadata)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}