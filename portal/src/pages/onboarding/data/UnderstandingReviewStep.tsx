import { useState } from "react";
import { Link } from "react-router-dom";
import { WIZARD_STEP_HEADINGS, type Suggestion, type Understanding } from "./types";

function FactCard({
  item,
  editing,
  business,
  setEditing,
  setBusiness,
  onReview,
  busy,
}: {
  item: Suggestion;
  editing: boolean;
  business: string;
  setEditing: (id: string | null) => void;
  setBusiness: (v: string) => void;
  onReview: (id: string, action: "confirm" | "change" | "ignore", payload?: Record<string, unknown>) => void;
  busy: string;
}) {
  const payload = item.payload || {};
  const value = String(payload.value ?? item.description ?? "");
  const page = payload.page;
  const evidence = Array.isArray(item.evidence) ? item.evidence[0] : undefined;
  return (
    <div key={item.id} className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">{item.title}</p>
        {item.confidence && (
          <span className="rounded bg-soft px-2 py-0.5 text-[11px] text-faint">
            {item.confidence}
          </span>
        )}
      </div>
      <p className="mt-1 text-base font-semibold text-text">{value}</p>
      {evidence && (
        <p className="mt-2 border-l-2 border-accent/40 pl-3 text-[13px] italic text-muted">
          “{evidence}”
        </p>
      )}
      {page != null && <p className="mt-1 text-xs text-faint">Página {String(page)}</p>}
      {editing ? (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onReview(item.id, "change", {
              ...payload,
              value: business.trim(),
            });
            setEditing(null);
          }}
        >
          <input
            className="input flex-1"
            placeholder="Valor correcto"
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
              setBusiness(value);
            }}
          >
            Corregir
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
  );
}

function MappingCard({
  item,
  editing,
  business,
  setEditing,
  setBusiness,
  onReview,
  busy,
}: {
  item: Suggestion;
  editing: boolean;
  business: string;
  setEditing: (id: string | null) => void;
  setBusiness: (v: string) => void;
  onReview: (id: string, action: "confirm" | "change" | "ignore", payload?: Record<string, unknown>) => void;
  busy: string;
}) {
  return (
    <div key={item.id} className="panel p-4">
      <p className="text-sm font-medium">{item.title}</p>
      <p className="text-[13px] text-muted">{item.description}</p>
      {item.confidence && (
        <p className="mt-1 text-xs text-faint">Confianza: {item.confidence}</p>
      )}
      {Array.isArray(item.evidence) && item.evidence.length > 1 && (
        <p className="mt-1 text-xs text-muted">
          Zent no está seguro. Opciones: {item.evidence.join(" · ")}
        </p>
      )}
      {editing ? (
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
  );
}

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

  const isDocument = understanding.flow === "documents" || understanding.kind === "document";

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold text-text">{WIZARD_STEP_HEADINGS.review}</h2>
      <p className="text-sm text-muted">
        {isDocument ? "Qué datos clave encontró Zent" : "Qué entendió Zent"}
      </p>
      {understanding.likely_entity && (
        <p className="text-sm">
          Entidad probable: <strong>{understanding.likely_entity}</strong>
          {understanding.row_count != null ? ` · ${understanding.row_count} filas` : ""}
        </p>
      )}
      {understanding.document_type && (
        <p className="text-sm">Tipo de documento: {understanding.document_type}</p>
      )}
      {understanding.pages != null && (
        <p className="text-sm text-muted">{understanding.pages} páginas</p>
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
      {suggestions.length === 0 ? (
        <p className="text-sm text-muted">
          Sin elementos para revisar. Puedes añadir una nota o continuar.
        </p>
      ) : (
        <div className="space-y-3">
          {suggestions.map((item) =>
            item.type === "document_fact" ? (
              <FactCard
                key={item.id}
                item={item}
                editing={editing === item.id}
                business={business}
                setEditing={setEditing}
                setBusiness={setBusiness}
                onReview={onReview}
                busy={busy}
              />
            ) : (
              <MappingCard
                key={item.id}
                item={item}
                editing={editing === item.id}
                business={business}
                setEditing={setEditing}
                setBusiness={setBusiness}
                onReview={onReview}
                busy={busy}
              />
            )
          )}
        </div>
      )}
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
          placeholder="Este dato significa…"
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
      <p className="text-sm text-muted">
        Los términos confirmados viven en Semántica.{" "}
        <Link to="/knowledge/glossary" className="text-accent underline">
          Abrir Semántica
        </Link>
      </p>
    </div>
  );
}