import {
  ArrowsClockwise,
  Copy,
  Eye,
  EyeSlash,
  Key as KeyIcon,
  ShieldCheck,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type TokenInfo = {
  prefix: string;
  name: string;
  last_used_at: string | null;
  created_at: string;
};

export default function KeysPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [info, setInfo] = useState<TokenInfo | null>(null);
  const [newToken, setNewToken] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(true);
  const [rotating, setRotating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<TokenInfo>("/api/v1/billing/token", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then(setInfo)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      pushToast("success", `${label} copiada`, "Ya está en tu portapapeles.");
    } catch {
      pushToast("error", "No se pudo copiar", "Copia el texto manualmente.");
    }
  }

  async function rotate() {
    if (!session) return;
    setError("");
    setMsg("");
    setRotating(true);
    setConfirming(false);
    try {
      const data = await api<{ token: string }>("/api/v1/billing/token/rotate", {
        method: "POST",
        token: session.token,
        tenantId: session.tenantId,
      });
      setNewToken(data.token);
      setRevealed(true);
      setMsg("Clave rotada. Guárdala ahora — no se vuelve a mostrar.");
      const refreshed = await api<TokenInfo>("/api/v1/billing/token", {
        token: session.token,
        tenantId: session.tenantId,
      });
      setInfo(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al rotar");
    } finally {
      setRotating(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Claves de integración"
        subtitle="Usa esta clave en tus sistemas externos. El portal ya te autentica con tu cuenta — no hace falta pegarla aquí."
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="panel">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
            <KeyIcon size={16} className="text-accent" aria-hidden />
            Clave actual
          </h2>
          {!loading && info && (
            <span className="badge badge-ok">
              <ShieldCheck size={13} aria-hidden /> Activa
            </span>
          )}
        </div>

        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={4} />
          </div>
        ) : info ? (
          <table className="table">
            <tbody>
              <tr>
                <th className="w-40">Prefijo</th>
                <td className="mono">{info.prefix}</td>
              </tr>
              <tr>
                <th>Nombre</th>
                <td>{info.name}</td>
              </tr>
              <tr>
                <th>Creado</th>
                <td>{fmtDateTime(info.created_at)}</td>
              </tr>
              <tr>
                <th>Último uso</th>
                <td>{info.last_used_at ? fmtDateTime(info.last_used_at) : "—"}</td>
              </tr>
              <tr>
                <th>Organización</th>
                <td className="mono">{session?.tenantId}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <EmptyState
            icon={KeyIcon}
            title="No hay clave disponible"
            body="Crea tu trial para generar la clave de integración."
          />
        )}

        {!loading && info && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-4">
            {confirming ? (
              <>
                <span className="text-sm text-warn">
                  La clave actual dejará de funcionar de inmediato. ¿Rotar?
                </span>
                <button
                  className="btn btn-danger"
                  type="button"
                  disabled={rotating}
                  onClick={() => void rotate()}
                >
                  {rotating ? <Spinner size={14} /> : <ArrowsClockwise size={15} aria-hidden />}
                  Sí, rotar
                </button>
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={() => setConfirming(false)}
                >
                  Cancelar
                </button>
              </>
            ) : (
              <button
                className="btn btn-danger"
                type="button"
                disabled={rotating}
                onClick={() => setConfirming(true)}
              >
                <ArrowsClockwise size={15} aria-hidden />
                Rotar clave
              </button>
            )}
          </div>
        )}
      </div>

      {newToken && (
        <div className="panel mt-4 border-accent/30">
          <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Nueva clave</h2>
            <span className="badge badge-pending">Cópiala ahora</span>
          </div>
          <div className="flex flex-col gap-2 p-5 sm:flex-row sm:items-center">
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 font-mono text-sm text-text outline-none focus:border-accent"
              readOnly
              value={revealed ? newToken : "•".repeat(48)}
              aria-label="Nueva clave"
            />
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                className="btn btn-secondary"
                aria-label={revealed ? "Ocultar clave" : "Mostrar clave"}
                onClick={() => setRevealed((r) => !r)}
              >
                {revealed ? <EyeSlash size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void copy(newToken, "Clave")}
              >
                <Copy size={15} aria-hidden />
                Copiar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
