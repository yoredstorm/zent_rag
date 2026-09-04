import { Bell, Buildings, Code, GearSix, Sparkle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComingSoon } from "../components/ComingSoon";
import { PageTabs } from "../components/PageTabs";
import {
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";

type OrgProfile = {
  name: string;
  company_name: string | null;
  country: string | null;
  email: string | null;
  phone: string | null;
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
  const [profile, setProfile] = useState<OrgProfile>({
    name: "",
    company_name: "",
    country: "",
    email: "",
    phone: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<OrgProfile>("/api/v1/organizations", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) =>
        setProfile({
          name: data.name || "",
          company_name: data.company_name || "",
          country: data.country || "",
          email: data.email || "",
          phone: data.phone || "",
        })
      )
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  async function save() {
    if (!session) return;
    setSaving(true);
    setError("");
    setMsg("");
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
      setMsg("Organización actualizada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Configuración"
        subtitle="Administra tu organización, workspace y preferencias de la plataforma."
      />
      <PageTabs tabs={TABS} active={tab} onChange={(id) => setTab(id as TabId)} idPrefix="settings" />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {tab === "general" && (
        <div className="panel mt-4 max-w-xl p-5">
          <h2 className="mb-3 text-sm font-semibold text-text">Perfil de la organización</h2>
          {loading ? (
            <SkeletonBlock rows={4} />
          ) : (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <label className="block text-sm">
                <span className="mb-1 block text-muted">Nombre</span>
                <input
                  className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                  value={profile.name}
                  onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value }))}
                  autoComplete="organization"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-muted">Empresa</span>
                <input
                  className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                  value={profile.company_name || ""}
                  onChange={(e) =>
                    setProfile((p) => ({ ...p, company_name: e.target.value }))
                  }
                  autoComplete="organization"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-muted">País</span>
                <input
                  className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                  value={profile.country || ""}
                  onChange={(e) => setProfile((p) => ({ ...p, country: e.target.value }))}
                  autoComplete="country-name"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-muted">Email</span>
                <input
                  type="email"
                  className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                  value={profile.email || ""}
                  onChange={(e) => setProfile((p) => ({ ...p, email: e.target.value }))}
                  autoComplete="email"
                />
              </label>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? <Spinner size={14} /> : null}
                Guardar
              </button>
            </form>
          )}
        </div>
      )}

      {tab === "workspace" && (
        <div className="mt-4 max-w-xl">
          <ComingSoon>
            Preferencias del workspace (identidad, entorno y regiones).{" "}
            <Link to="/workspaces" className="text-accent underline underline-offset-2">
              Administra tus workspaces aquí.
            </Link>
          </ComingSoon>
        </div>
      )}

      {tab === "ai" && (
        <div className="mt-4 max-w-xl">
          <ComingSoon>
            Configuración de IA: modelos por defecto, límites y parámetros de generación.
            Disponible en una próxima fase.
          </ComingSoon>
        </div>
      )}

      {tab === "notifications" && (
        <div className="mt-4 max-w-xl">
          <ComingSoon>
            <Link to="/notifications" className="text-accent underline underline-offset-2">
              Revisa tus notificaciones aquí.
            </Link>{" "}
            Las preferencias de canales y frecuencia llegarán en una próxima fase.
          </ComingSoon>
        </div>
      )}

      {tab === "developer" && (
        <div className="mt-4 max-w-xl">
          <ComingSoon>
            <Link to="/developers" className="text-accent underline underline-offset-2">
              Centro de desarrolladores
            </Link>{" "}
            para credenciales, webhooks y documentación de la API.
          </ComingSoon>
        </div>
      )}
    </div>
  );
}