import { useState } from "react";
import type { Suggestion, Understanding } from "./types";

export function UnderstandingReviewStep({
  understanding,
  suggestions,
  onReview,
  onFreeText,
  onSkip,
  busy,
}: {
  understanding: Understanding;
  suggestions: Suggestion[];
  onReview: (id: string, action: "confirm" | "change" | "ignore", payload?: Record<string, unknown>) => void;
  onFreeText: (text: string) => void;
  onSkip: () => void;
  busy: string;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [business, setBusiness] = useState("");
  const [note, setNote] = useState("");

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold text-text">Qué entendió Zent</h2>
      {understanding.likely_entity && (
        <p className="text-sm">
          Entidad probable: <strong>{understanding.likely_entity}</strong>
          {understanding.row_count != null ? ` · ${understanding.row_count} filas` : ""}
        </p>
      )}
      {understanding.document_type && (
        <p className="text-sm">Tipo de documento: {understanding.document_type}</p>
      )}
      {understanding.topics && understanding.topics.length > 0 && (
        <p className="text-sm text-muted">Temas: {understanding.topics.join(", ")}</p>
      )}
      {understanding.entities && understanding.entities.length > 0 && (
        <p className="text-sm">Detectó: {understanding.entities.map((e) => e.name).join(", ")}</p>
      )}
      {understanding.relationships && understanding.relationships.length > 0 && (
        <ul className="text-sm text-muted">
          {understanding.relationships.map((rel, i) => (
            <li key={i}>
              {rel.from} — {rel.to}
            </li>
          ))}
        </ul>
      )}
      {understanding.columns && understanding.columns.length > 0 && (
        <div className="overflow-x-auto">
          <table className="table text-sm">
            <thead>
              <tr>
                <th>Columna</th>
                <th>Tipo</th>
                <th>Nulos</th>
              </tr>
            </thead>
            <tbody>
              {understanding.columns.map((col) => (
                <tr key={col.physical_name}>
                  <td>{col.physical_name}</td>
                  <td className="text-muted">{col.inferred_type || "—"}</td>
                  <td className="text-muted">
                    {col.null_ratio != null ? `${Math.round(col.null_ratio * 100)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="space-y-3">
        {suggestions.map((item) => (
          <div key={item.id} className="panel p-4">
            <p className="text-sm font-medium">{item.title}</p>
            <p className="text-[13px] text-muted">{item.description}</p>
            {item.confidence && (
              <p className="mt-1 text-xs text-faint">Confianza: {item.confidence}</p>
            )}
            {Array.isArray(item.evidence) && item.evidence.length > 1 && (
              <p className="mt-1 text-xs text-muted">Zent no está seguro. Opciones: {item.evidence.join(" · ")}</p>
            )}
            {editing === item.id ? (
              <form
                className="mt-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  onReview(item.id, "change", {
                    ...item.payload,
                    business_name: business,
                    display_name: business,
                  });
                  setEditing(null);
                }}
              >
                <input
                  className="input flex-1"
                  placeholder="Nombre de negocio"
                  value={business}
                  onChange={(e) => setBusiness(e.target.value)}
                />
                <button type="submit" className="btn btn-primary">
                  Guardar
                </button>
              </form>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn btn-primary"
                  data-testid="review-confirm"
                  disabled={busy === item.id}
                  onClick={() => onReview(item.id, "confirm")}
                >
                  Confirmar
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setEditing(item.id);
                    setBusiness(String(item.payload.business_name || item.title));
                  }}
                >
                  Cambiar
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy === item.id}
                  onClick={() => onReview(item.id, "ignore")}
                >
                  Ignorar
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (note.trim()) {
            onFreeText(note.trim());
            setNote("");
          }
        }}
      >
        <input
          className="input flex-1"
          placeholder="Este campo es la tarifa publicada sin impuesto…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button type="submit" className="btn btn-secondary">
          Añadir nota
        </button>
      </form>
      <button type="button" className="text-xs text-muted" onClick={onSkip}>
        Saltar revisión
      </button>
    </div>
  );
}
