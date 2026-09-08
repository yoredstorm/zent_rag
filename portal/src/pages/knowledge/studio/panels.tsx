import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api";

type LexRow = {
  id: string;
  token: string;
  meaning: string;
  role: string;
  status: string;
};

type AuthOpts = { token?: string; organizationId: string };

export function LexiconPanel({ onClose, auth }: { onClose: () => void; auth?: AuthOpts }) {
  const [rows, setRows] = useState<LexRow[]>([]);
  const [token, setToken] = useState("");
  const [meaning, setMeaning] = useState("");
  const [role, setRole] = useState("UNKNOWN");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<LexRow[]>("/api/v1/catalog/lexicon", auth)
      .then(setRows)
      .catch((e) => setError(String(e)));
  }, [auth]);

  useEffect(() => load(), [load]);

  const save = async () => {
    setError("");
    try {
      await api("/api/v1/catalog/lexicon", {
        method: "PUT",
        body: JSON.stringify({ token, meaning, role, status: "signal" }),
        ...auth,
      });
      setToken("");
      setMeaning("");
      load();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="card p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Léxico de la organización</h3>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Cerrar
        </button>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        Señales, nunca verdad global. El mismo token puede significar otra cosa en otra organización.
      </p>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          className="input"
          placeholder="Token (DSC)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          aria-label="Token"
        />
        <input
          className="input"
          placeholder="Significado"
          value={meaning}
          onChange={(e) => setMeaning(e.target.value)}
          aria-label="Significado"
        />
        <select className="input" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Rol">
          <option value="UNKNOWN">UNKNOWN</option>
          <option value="IDENTIFIER">IDENTIFIER</option>
          <option value="DESCRIPTION">DESCRIPTION</option>
          <option value="MEASURE">MEASURE</option>
          <option value="DATE">DATE</option>
          <option value="STATUS">STATUS</option>
        </select>
        <button type="button" className="btn btn-sm btn-primary" onClick={save} disabled={!token || !meaning}>
          Guardar señal
        </button>
      </div>
      <ul className="mt-3 max-h-40 space-y-1 overflow-auto text-xs">
        {rows.map((r) => (
          <li key={r.id}>
            <span className="font-mono">{r.token}</span> → {r.meaning} ({r.role}, {r.status})
          </li>
        ))}
        {rows.length === 0 && <li className="text-zinc-400">Sin entradas todavía</li>}
      </ul>
    </div>
  );
}

export function FreeTextDraft({
  columnId,
  onCreated,
  auth,
}: {
  columnId?: string;
  onCreated: () => void;
  auth?: AuthOpts;
}) {
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const submit = async () => {
    setMsg("");
    try {
      const result = await api<{ needs_confirm: boolean; name: string }>("/api/v1/catalog/studio/free-text", {
        method: "POST",
        body: JSON.stringify({ text, column_id: columnId || null }),
        ...auth,
      });
      setMsg(`Borrador «${result.name}». Confirma en el panel para aprobar.`);
      setText("");
      onCreated();
    } catch (e) {
      setMsg(String(e));
    }
  };
  return (
    <div className="mt-3">
      <label className="text-xs text-zinc-500" htmlFor="studio-freetext">
        Describe el campo en tus palabras
      </label>
      <textarea
        id="studio-freetext"
        className="input mt-1 w-full"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button type="button" className="btn btn-sm mt-2" onClick={submit} disabled={!text.trim()}>
        Crear borrador
      </button>
      {msg && <p className="mt-1 text-xs text-zinc-600">{msg}</p>}
    </div>
  );
}

export function groupLabel(group: string) {
  return (
    {
      high: "Alta confianza",
      needs_review: "Necesita revisión",
      unknown: "Desconocido",
      approved: "Aprobado",
    } as Record<string, string>
  )[group] || group;
}

export const GROUP_ORDER = ["high", "needs_review", "unknown", "approved"] as const;

export function impactHint(role?: string) {
  if (role === "IDENTIFIER" || role === "MEASURE" || role === "DATE") return "Prioridad alta";
  return "";
}
