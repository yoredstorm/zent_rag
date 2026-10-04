import { ArrowCounterClockwise, Bell, Buildings, Code, GearSix, MagnifyingGlass, Sparkle, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import ResidencyPanel from "../components/ResidencyPanel";
import { fmtNum } from "../lib/format";
import {
  exitImpersonationToPlatform,
  hasPlatformSession,
  isImpersonating,
} from "../lib/impersonation";
import {
  Badge,
  Button,
  ButtonLink,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  Input,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  SaveStatus,
  SkeletonBlock,
  SuccessInline,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type SaveState,
} from "../components/ui";

type OrgProfile = {
  name: string;
  company_name: string | null;
  country: string | null;
  email: string | null;
  phone: string | null;
};

const EMPTY_PROFILE: OrgProfile = {
  name: "",
  company_name: "",
  country: "",
  email: "",
  phone: "",
};

const TABS = [
  { id: "general", label: "General", icon: GearSix },
  { id: "workspace", label: "Workspace", icon: Buildings },
  { id: "ai", label: "IA", icon: Sparkle },
  { id: "notifications", label: "Notificaciones", icon: Bell },
  { id: "developer", label: "Desarrollador", icon: Code },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function SettingsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<TabId>("general");
  const [profile, setProfile] = useState<OrgProfile>(EMPTY_PROFILE);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setLoadError("");
    api<OrgProfile>("/api/v1/organizations", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        setProfile({
          name: data.name || "",
          company_name: data.company_name || "",
          country: data.country || "",
          email: data.email || "",
          phone: data.phone || "",
        });
        setSaveState("idle");
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  function update(patch: Partial<OrgProfile>) {
    setProfile((p) => ({ ...p, ...patch }));
    setSaveState("dirty");
    setSaveError("");
  }

  async function save() {
    if (!session) return;
    setSaveState("saving");
    setSaveError("");
    try {
      await api("/api/v1/organizations", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: profile.name,
          company_name: profile.company_name,
          country: profile.country,
          email: profile.email,
          phone: profile.phone,
        }),
      });
      setSaveState("saved");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Error al guardar");
      setSaveState("error");
    }
  }

  const canSave = saveState === "dirty" || saveState === "error";

  return (
    <div>
      <PageHeader
        title="Configuración"
        subtitle="Administra tu organización, workspace y preferencias de la plataforma."
      />
      <Tabs value={tab} onValueChange={(value) => setTab(value as TabId)}>
        <TabsList>
          {TABS.map(({ id, label, icon }) => (
            <TabsTrigger key={id} value={id} icon={icon}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="general">
          <ErrorInline message={loadError} className="mb-4" />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
            <Panel>
              <PanelHeader
                title="Perfil de la organización"
                description="Datos legales y de contacto que Zent usa en la plataforma."
                actions={<SaveStatus state={saveState} error={saveError} />}
              />
              {loading ? (
                <div className="panel-body">
                  <SkeletonBlock rows={4} />
                </div>
              ) : (
                <form
                  className="panel-body"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void save();
                  }}
                >
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field
                      label="Nombre"
                      hint="Nombre visible de la organización en el portal."
                      className="sm:col-span-2"
                    >
                      <Input
                        value={profile.name}
                        onChange={(e) => update({ name: e.target.value })}
                        autoComplete="organization"
                        required
                      />
                    </Field>
                    <Field label="Empresa">
                      <Input
                        value={profile.company_name || ""}
                        onChange={(e) => update({ company_name: e.target.value })}
                        autoComplete="organization"
                      />
                    </Field>
                    <Field label="País">
                      <Input
                        value={profile.country || ""}
                        onChange={(e) => update({ country: e.target.value })}
                        autoComplete="country-name"
                      />
                    </Field>
                    <Field label="Email">
                      <Input
                        type="email"
                        value={profile.email || ""}
                        onChange={(e) => update({ email: e.target.value })}
                        autoComplete="email"
                      />
                    </Field>
                    <Field label="Teléfono">
                      <Input
                        type="tel"
                        value={profile.phone || ""}
                        onChange={(e) => update({ phone: e.target.value })}
                        autoComplete="tel"
                      />
                    </Field>
                  </div>
                  <FormActions sticky className="mt-6">
                    <SaveStatus state={saveState} error={saveError} />
                    <Button type="submit" variant="primary" loading={saveState === "saving"} disabled={!canSave}>
                      Guardar cambios
                    </Button>
                  </FormActions>
                </form>
              )}
            </Panel>

            <aside className="space-y-4 lg:sticky lg:top-6">
              <Panel>
                <PanelHeader title="Contexto" description="Los cambios aplican a toda la organización." />
                <div className="panel-body">
                  <KeyValue
                    items={[
                      { key: "Organización", value: session?.companyName || "—" },
                      { key: "Workspace", value: session?.workspaceId || "—", mono: true },
                      { key: "Rol", value: session?.roles?.join(", ") || "—" },
                      { key: "ID de organización", value: session?.organizationId || "—", mono: true },
                    ]}
                  />
                </div>
              </Panel>
              <ControlCenterSwitchPanel />
            </aside>
          </div>
        </TabsContent>

        <TabsContent value="workspace" className="space-y-4">
          <Panel>
            <PanelHeader
              title="Workspaces"
              description="Espacios de trabajo: agrupa agentes, knowledge bases y conectores."
              actions={
                <ButtonLink to="/workspaces" variant="secondary">
                  Administrar workspaces
                </ButtonLink>
              }
            />
            <div className="panel-body text-[13px] leading-relaxed text-muted">
              Cada workspace define el alcance de tus agentes y fuentes. La configuración de
              residencia de datos se resuelve por organización.
            </div>
          </Panel>
          <ResidencyPanel session={session} />
          <WorkspaceResetPanel />
          <SelfPurgePanel />
        </TabsContent>

        <TabsContent value="ai">
          <Panel>
            <EmptyState
              icon={Sparkle}
              tone="accent"
              title="Configuración de IA"
              body="Modelos por defecto, límites y parámetros de generación."
              hint="Disponible en una próxima fase."
            />
          </Panel>
        </TabsContent>

        <TabsContent value="notifications">
          <Panel>
            <EmptyState
              icon={Bell}
              title="Preferencias de notificación"
              body="Canales, frecuencia y silencios por evento llegarán en una próxima fase."
              hint="Mientras tanto, el centro de notificaciones sigue operativo."
              action={
                <ButtonLink to="/notifications" variant="secondary">
                  Ver notificaciones
                </ButtonLink>
              }
            />
          </Panel>
        </TabsContent>

        <TabsContent value="developer">
          <Panel>
            <EmptyState
              icon={Code}
              title="Centro de desarrolladores"
              body="Credenciales, webhooks y documentación de la API."
              action={
                <ButtonLink to="/developers" variant="secondary">
                  Abrir centro de desarrolladores
                </ButtonLink>
              }
            />
          </Panel>
        </TabsContent>
      </Tabs>
    </div>
  );
}

const RESET_SCOPES = [
  { key: "documents", label: "Documentos subidos" },
  { key: "sources", label: "Conexiones de fuentes" },
  { key: "semantic", label: "Mapeos semánticos" },
  { key: "agents", label: "Agentes" },
  { key: "all_business_data", label: "Datos de negocio (reinicio total)" },
] as const;

function WorkspaceResetPanel() {
  const { session } = useAuth();
  const [scopes, setScopes] = useState<Record<(typeof RESET_SCOPES)[number]["key"], boolean>>({
    documents: false,
    sources: false,
    semantic: false,
    agents: false,
    all_business_data: false,
  });
  const [confirm, setConfirm] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const selected = RESET_SCOPES.filter((scope) => scopes[scope.key]);
  const ready = confirm.trim() === "RESET" && !busy;

  async function run() {
    if (!session) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api("/api/v1/demo-transition/reset", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          confirmation: confirm,
          documents: scopes.documents,
          sources: scopes.sources,
          semantic: scopes.semantic,
          agents: scopes.agents,
          all_business_data: scopes.all_business_data,
        }),
      });
      setMsg("Reinicio ejecutado.");
      setConfirm("");
      setConfirmOpen(false);
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="border-danger/25">
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            Reinicio de datos
            <Badge tone="danger">Zona de riesgo</Badge>
          </span>
        }
        description="Elimina datos de la organización de forma selectiva. No se puede deshacer."
      />
      <div className="panel-body">
        <ErrorInline message={err} />
        <SuccessInline message={msg} />
        <fieldset className="grid gap-2.5 sm:grid-cols-2">
          <legend className="eyebrow mb-2">Alcance</legend>
          {RESET_SCOPES.map((scope) => (
            <Checkbox
              key={scope.key}
              checked={scopes[scope.key]}
              onCheckedChange={(checked) =>
                setScopes((current) => ({ ...current, [scope.key]: checked }))
              }
              label={scope.label}
            />
          ))}
        </fieldset>
        <div className="mt-4 max-w-xs">
          <Field
            label="Confirmación"
            hint={
              <>
                Escribe <span className="mono text-text">RESET</span> para habilitar la acción.
              </>
            }
          >
            <Input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="off"
              placeholder="RESET"
            />
          </Field>
        </div>
      </div>
      <div className="panel-footer justify-end">
        <Button
          variant="danger"
          leadingIcon={ArrowCounterClockwise}
          disabled={!ready}
          onClick={() => setConfirmOpen(true)}
        >
          Reiniciar datos
        </Button>
      </div>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Reiniciar datos de la organización"
        body={
          selected.length > 0
            ? `Se eliminarán: ${selected.map((scope) => scope.label).join(", ")}. Esta acción no se puede deshacer.`
            : "No hay alcances seleccionados: el reinicio se ejecutará sin eliminar datos."
        }
        confirmLabel="Ejecutar reinicio"
        loading={busy}
        onConfirm={() => void run()}
      />
    </Panel>
  );
}

type SelfPurgeStatus = { enabled: boolean; allowed: boolean; email: string | null };

type SelfPurgePreview = {
  tables: Record<string, number>;
  tables_total: number;
  truncated: boolean;
  total_rows: number;
  uploads_bytes: number;
  dsr_artifacts: number;
};

type SelfPurgeResult = {
  status: string;
  before: { total_rows: number; tables_total: number };
  after: { total_rows: number; tables_total: number };
  failures: Array<{ table: string; error: string }>;
};

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** Solo visible para emails en RAG_SELF_PURGE_EMAILS (lo decide el backend). */
function SelfPurgePanel() {
  const { session, logout } = useAuth();
  const [status, setStatus] = useState<SelfPurgeStatus | null>(null);
  const [preview, setPreview] = useState<SelfPurgePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<SelfPurgeResult | null>(null);

  useEffect(() => {
    if (!session) return;
    api<SelfPurgeStatus>("/api/v1/self-purge/status", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [session]);

  if (!status?.allowed) return null;

  const email = status.email || "";
  const ready = confirm.trim().toLowerCase() === email.toLowerCase() && !busy;

  async function loadPreview() {
    if (!session) return;
    setPreviewBusy(true);
    setErr("");
    try {
      setPreview(
        await api<SelfPurgePreview>("/api/v1/self-purge/preview", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      );
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Error");
    } finally {
      setPreviewBusy(false);
    }
  }

  async function run() {
    if (!session) return;
    setBusy(true);
    setErr("");
    try {
      const data = await api<SelfPurgeResult>("/api/v1/self-purge/execute", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ confirmation: confirm }),
      });
      setResult(data);
      setConfirmOpen(false);
      setPreview(null);
      setConfirm("");
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Error");
      setConfirmOpen(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="border-danger/25">
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            Borrado total de mi rastro
            <Badge tone="danger">Irreversible</Badge>
          </span>
        }
        description="Borra toda la data de esta organización en todos los workspaces: documentos, agentes, conversaciones, grafo de compañía, memoria, aprendizaje, auditoría, vectores y uploads. Conserva tu usuario, tu acceso y la suscripción."
      />
      <div className="panel-body space-y-4">
        <ErrorInline message={err} />
        {result ? (
          <div className="space-y-3">
            <SuccessInline
              message={`Borrado ejecutado: ${fmtNum(result.before.total_rows)} filas en ${fmtNum(result.before.tables_total)} tablas quedaron en ${fmtNum(result.after.total_rows)}.`}
            />
            {result.failures.length > 0 && (
              <p className="text-[13px] text-danger">
                {fmtNum(result.failures.length)} objetivos no se limpiaron por completo:{" "}
                {result.failures.map((failure) => failure.table).join(", ")}. Vuelve a
                ejecutar para reintentar (es idempotente).
              </p>
            )}
            <div className="flex justify-end">
              <Button
                variant="danger"
                onClick={() => {
                  logout();
                  window.location.assign("/login");
                }}
              >
                Empezar de cero
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                leadingIcon={MagnifyingGlass}
                loading={previewBusy}
                onClick={() => void loadPreview()}
              >
                Ver impacto
              </Button>
              {preview && (
                <span className="text-[13px] text-muted">
                  {fmtNum(preview.total_rows)} filas en {fmtNum(preview.tables_total)}{" "}
                  tablas · uploads {formatBytes(preview.uploads_bytes)} · artefactos DSR{" "}
                  {fmtNum(preview.dsr_artifacts)}
                </span>
              )}
            </div>
            {preview && Object.keys(preview.tables).length > 0 && (
              <ul className="space-y-1 text-[13px]">
                {Object.entries(preview.tables).map(([table, count]) => (
                  <li key={table} className="flex justify-between gap-3">
                    <span className="mono">{table}</span>
                    <span className="text-muted">{fmtNum(count)}</span>
                  </li>
                ))}
              </ul>
            )}
            {preview?.truncated && (
              <p className="text-xs text-faint">
                Se listan las {fmtNum(Object.keys(preview.tables).length)} tablas con más
                filas.
              </p>
            )}
            <div className="max-w-xs">
              <Field
                label="Confirmación"
                hint={
                  <>
                    Escribe <span className="mono text-text">{email}</span> para habilitar
                    el borrado.
                  </>
                }
              >
                <Input
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="off"
                  placeholder={email}
                />
              </Field>
            </div>
          </>
        )}
      </div>
      {!result && (
        <div className="panel-footer justify-end">
          <Button
            variant="danger"
            leadingIcon={Trash}
            disabled={!ready}
            onClick={() => setConfirmOpen(true)}
          >
            Borrar todo mi rastro
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Borrar toda la data de la organización"
        body="Se eliminará toda la data de la organización en todos los workspaces: documentos, agentes, conversaciones, grafo de compañía, memoria, aprendizaje, auditoría, vectores y uploads. Se conservan tu usuario, tu acceso y la suscripción. Esta acción no se puede deshacer."
        confirmLabel="Borrar todo"
        loading={busy}
        onConfirm={() => void run()}
      />
    </Panel>
  );
}

/**
 * Cambio de pantalla hacia el Control Center (modo pruebas).
 * Si la sesión actual es impersonada, la revoca al volver; si hay sesión de
 * plataforma guardada, navega directo; si no, ofrece el login de plataforma.
 */
function ControlCenterSwitchPanel() {
  const [busy, setBusy] = useState(false);
  const impersonating = isImpersonating();
  const platformSession = hasPlatformSession();

  async function backToControlCenter() {
    setBusy(true);
    await exitImpersonationToPlatform({ returnTo: "/control-center/settings" });
  }

  return (
    <Panel>
      <PanelHeader
        title="Control Center"
        description="Cambia entre el portal de cliente y la consola de plataforma."
      />
      <div className="panel-body flex flex-col items-start gap-3 text-[13px] leading-relaxed text-muted">
        {impersonating ? (
          <>
            <p>
              Estás operando como{" "}
              <span className="font-medium text-text">{impersonating}</span>. Al volver se
              cierra la sesión de usuario y regresas al Control Center.
            </p>
            <Button
              variant="secondary"
              loading={busy}
              onClick={() => void backToControlCenter()}
            >
              Volver al Control Center
            </Button>
          </>
        ) : platformSession ? (
          <>
            <p>Hay una sesión de plataforma activa en este navegador.</p>
            <Button
              variant="secondary"
              onClick={() => window.location.assign("/control-center")}
            >
              Ir al Control Center
            </Button>
          </>
        ) : (
          <>
            <p>Para la consola de plataforma inicia sesión con tu cuenta de administrador.</p>
            <ButtonLink to="/control-center/login" variant="secondary">
              Abrir Control Center
            </ButtonLink>
          </>
        )}
      </div>
    </Panel>
  );
}
