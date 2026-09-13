import { useState } from "react";
import { Link } from "react-router-dom";
import { WIZARD_STEP_HEADINGS, type Suggestion, type Understanding } from "./types";
import { selectDigestHighlights } from "./wizardUx";

function itemValue(item: Suggestion): string {
  const payload = item.payload || {};
  return String(payload.value ?? payload.business_name ?? item.description ?? "");
}

function restCountLabel(n: number): string {
  return n === 1 ? "1 dato más" : `${n} datos más`;
}

function DigestRow({
  item,
  expanded,
  editing,
  draft,
  busy,
  onToggle,
  onStartEdit,
  onDraft,
  onReview,
}: {
  item: Suggestion;
  expanded: boolean;
  editing: boolean;
  draft: string;
  busy: string;
  onToggle: () => void;
  onStartEdit: () => void;
  onDraft: (value: string) => void;
  onReview: (id: string, action: "confirm" | "change" | "ignore", payload?: Record<string, unknown>) => void;
}) {
  const value = itemValue(item);
  const evidence = Array.isArray(item.evidence) ? item.evidence[0] : undefined;
  const isFact = item.type === "document_fact";

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        data-testid={`digest-row-${item.id}`}
        className="flex w-full items-start justify-between gap-3 py-3 text-left min-h-11"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="text-sm text-muted">{item.title}</span>
        <span className="text-sm font-medium text-text">{value || "—"}</span>
      </button>
      {expanded && (
        <div className="pb-3 space-y-2">
          {evidence && (
            <p className="border-l-2 border-accent/40 pl-3 text-[13px] italic text-muted">
              “{evidence}”
            </p>
          )}
          {editing ? (
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const next = draft.trim();
                onReview(
                  item.id,
                  "change",
                  isFact
                    ? { ...item.payload, value: next }
                    : { ...item.payload, business_name: next, display_name: next }
                );
              }}
            >
              <input
                className="input flex-1"
                aria-label="Valor correcto"
                value={draft}
                onChange={(e) => onDraft(e.target.value)}
              />
              <button type="submit" className="btn btn-primary">
                Guardar
              </button>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-secondary" onClick={onStartEdit}>
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
  onAcceptAll,
  busy,
}: {
  understanding: Understanding;
  suggestions: Suggestion[];
  onReview: (id: string, action: "confirm" | "change" | "ignore", payload?: Record<string, unknown>) => void;
  onFreeText: (text: string) => void;
  onSkip: () => void;
  onAcceptAll: () => void;
  busy: string;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [showRest, setShowRest] = useState(false);

  const isDocument = understanding.flow === "documents" || understanding.kind === "document";
  const { highlights, rest } = selectDigestHighlights(suggestions, {
    flow: understanding.flow,
    kind: understanding.kind,
  });

  function toggle(id: string) {
    setExpanded((current) => (current === id ? null : id));
    setEditing(null);
  }

  function startEdit(item: Suggestion) {
    setEditing(item.id);
    setDraft(itemValue(item));
  }

  function renderRows(items: Suggestion[]) {
    return items.map((item) => (
      <DigestRow
        key={item.id}
        item={item}
        expanded={expanded === item.id}
        editing={editing === item.id}
        draft={draft}
        busy={busy}
        onToggle={() => toggle(item.id)}
        onStartEdit={() => startEdit(item)}
        onDraft={setDraft}
        onReview={(id, action, payload) => {
          if (payload) onReview(id, action, payload);
          else onReview(id, action);
          setEditing(null);
          setExpanded(null);
        }}
      />
    ));
  }

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
      {suggestions.length === 0 ? (
        <p className="text-sm text-muted">
          Sin elementos para revisar. Puedes añadir una nota o continuar.
        </p>
      ) : (
        <div className="panel px-4">
          {renderRows(highlights)}
          {rest.length > 0 && (
            <div className="py-2">
              <button
                type="button"
                className="text-sm text-accent min-h-11"
                onClick={() => setShowRest((v) => !v)}
                aria-expanded={showRest}
              >
                {showRest ? "Ocultar" : restCountLabel(rest.length)}
              </button>
              {showRest && renderRows(rest)}
            </div>
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
      <button
        type="button"
        className="btn btn-primary"
        data-testid="goto-questions"
        disabled={busy === "accept-all"}
        onClick={onAcceptAll}
      >
        Se ve bien
      </button>
      <button type="button" className="block text-xs text-muted" onClick={onSkip}>
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
