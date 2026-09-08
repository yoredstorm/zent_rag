import { useEffect, useState } from "react";
import { STEP_UP_REQUIRED_EVENT } from "../lib/errors";
import { api, loadSession, saveSession } from "../api";
import { useAuth } from "../auth";
import { Spinner } from "./ui";

export function TenantStepUpModal() {
  const { session, applySession } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    function onStepUpRequired() {
      setOpen(true);
      setError("");
      setPassword("");
      setCode("");
    }
    window.addEventListener(STEP_UP_REQUIRED_EVENT, onStepUpRequired);
    return () => window.removeEventListener(STEP_UP_REQUIRED_EVENT, onStepUpRequired);
  }, []);

  if (!open || !session) return null;

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const data = await api<{ access_token: string }>("/api/v1/auth/step-up", {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        body: JSON.stringify({ password, code }),
      });
      const next = { ...loadSession()!, token: data.access_token };
      saveSession(next);
      applySession(next);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-sm rounded-md border border-border bg-surface p-4">
        <h2 className="mb-2 font-semibold">Confirma para continuar</h2>
        <input
          type="password"
          className="input mb-2"
          placeholder="Contraseña"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <input
          className="input mb-2"
          placeholder="Código MFA (si aplica)"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        {error && <p className="text-sm text-danger">{error}</p>}
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void confirm()}>
          {busy ? <Spinner size={14} /> : "Confirmar"}
        </button>
      </div>
    </div>
  );
}
