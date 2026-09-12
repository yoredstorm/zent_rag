import { BookOpen, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { isApiError } from "../../lib/errors";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

type GlossaryTerm = {
  id: string;
  concept: string;
  definition: string;
  synonyms: string[];
  owner: string | null;
  status: string;
  version: number;
  provenance: string;
};

export default function KnowledgeGlossaryPage() {
  const { session } = useAuth();
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [concept, setConcept] = useState("");
  const [definition, setDefinition] = useState("");
  const [synonyms, setSynonyms] = useState("");
  const [saving, setSaving] = useState(false);
  const inflight = useRef(false);

  const load = useCallback(() => {
    if (!session || inflight.current) return;
    inflight.current = true;
    setLoading(true);
    api<GlossaryTerm[]>("/api/v1/catalog/glossary", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setTerms)
      .catch((e) => {
        if (isApiError(e)) {
          setError(
            e.status === 401 || e.status === 403
              ? "Sin permiso para el glosario de catálogo (catalog:read). Habla con el admin de tu organización."
              : e.message,
          );
        } else {
          setError(String(e));
        }
      })
      .finally(() => {
        inflight.current = false;
        setLoading(false);
      });
  }, [session]);

  // Dep estable (session puede ser un objeto nuevo en cada render → evita loop)
  useEffect(() => load(), [load]);

  const save = async () => {
    if (!session || !concept.trim() || !definition.trim()) return;
    setSaving(true);
    try {
      await api("/api/v1/catalog/glossary", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          concept,
          definition,
          synonyms: synonyms.split(",").map((s) => s.trim()).filter(Boolean),
          status: "draft",
        }),
      });
      setConcept("");
      setDefinition("");
      setSynonyms("");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <KnowledgeLayout>
      <PageHeader title={KNOWLEDGE_HEADINGS.glossary} subtitle="Términos empresariales con synonyms, owner y versionado (solo lo aprobado alimenta las respuestas)." />
      {error && <ErrorInline message={error} />}

      <div className="card mb-4 p-4">
        <div className="text-sm font-medium text-zinc-600">Nuevo término</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_2fr_1fr]">
          <input
            className="input"
            placeholder="concepto (p.ej. cliente activo)"
            value={concept}
            onChange={(e) => setConcept(e.target.value)}
          />
          <input
            className="input"
            placeholder="definición"
            value={definition}
            onChange={(e) => setDefinition(e.target.value)}
          />
          <input
            className="input"
            placeholder="sinónimos (coma separada)"
            value={synonyms}
            onChange={(e) => setSynonyms(e.target.value)}
          />
        </div>
        <button className="btn btn-primary mt-2" onClick={save} disabled={saving}>
          <Plus size={14} /> Guardar (draft)
        </button>
      </div>

      {loading ? (
        <SkeletonBlock rows={4} />
      ) : terms.length === 0 ? (
        <EmptyState icon={BookOpen} title="Sin términos aún" />
      ) : (
        <div className="space-y-2">
          {terms.map((t) => (
            <div key={t.id} className="card p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">{t.concept}</span>
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={`rounded-full px-2 py-0.5 ${
                      t.status === "approved"
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {t.status} · v{t.version}
                  </span>
                  <span className="text-zinc-400">{t.provenance}</span>
                </div>
              </div>
              <div className="mt-1 text-sm text-zinc-600">{t.definition}</div>
              {t.synonyms.length > 0 && (
                <div className="mt-1 text-xs text-zinc-400">
                  Sinónimos: {t.synonyms.join(", ")}
                </div>
              )}
              {t.owner && <div className="mt-1 text-xs text-zinc-400">Owner: {t.owner}</div>}
            </div>
          ))}
        </div>
      )}
    </KnowledgeLayout>
  );
}