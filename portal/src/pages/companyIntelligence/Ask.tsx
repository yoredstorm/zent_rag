import { MagnifyingGlass, Sparkle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  Button,
  ErrorInline,
  InfoInline,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
  Textarea,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import { COPY, INTENT_LABELS, statusLabelFor, statusToneFor } from "./companyCopy";

type Evidence = {
  kind: string;
  ref: string;
  label: string;
  detail: Record<string, unknown>;
};

type Answer = {
  question: string;
  intent: string;
  answer: string;
  certainty: string;
  decision: {
    provider: string;
    intent: string;
    confidence: number;
    fallback_used: boolean;
    reason?: string;
  };
  evidence: Evidence[];
  context_used: {
    tokens_estimate: number | null;
    truncated: boolean | null;
    concepts: number;
    mappings: number;
    processes: number;
    systems: number;
    memories: number;
  };
  followups: string[];
};

const EVIDENCE_LINKS: Record<string, string> = {
  entity: "/company-intelligence/entity/",
  mapping: "/company-intelligence/entity/",
  path: "/company-intelligence/entity/",
  system: "/company-intelligence/entity/",
  agent: "/company-intelligence/entity/",
};

export default function CompanyAskPage() {
  const { session } = useAuth();
  // Si se llega desde la página de una entidad, esa entidad es el contexto.
  const { entityId } = useParams();
  const [question, setQuestion] = useState("");
  const [examples, setExamples] = useState<string[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const data = await api<{ items: string[] }>(
          "/api/v1/company-intelligence/ask/examples",
          { token: session.token, organizationId: session.organizationId },
        );
        setExamples(data.items || []);
      } catch {
        setExamples([]);
      }
    })();
  }, [session]);

  const ask = async (value: string) => {
    if (!session || !value.trim()) return;
    setLoading(true);
    setError("");
    try {
      setAnswer(
        await api<Answer>("/api/v1/company-intelligence/ask", {
          token: session.token,
          organizationId: session.organizationId,
          method: "POST",
          body: JSON.stringify({
            question: value,
            // Contexto de página: "¿esta tabla?" se resuelve sin repetir el nombre.
            entity_id: entityId || undefined,
          }),
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo responder");
      setAnswer(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.ask}
        subtitle="Preguntas sobre cómo funciona la empresa. La respuesta se arma con el grafo y viaja con su evidencia."
      />
      <ErrorInline message={error} />

      <Panel>
        <label className="text-sm" htmlFor="company-ask-input">
          <span className="text-muted">Pregunta</span>
        </label>
        <Textarea
          id="company-ask-input"
          data-testid="company-ask-input"
          value={question}
          placeholder={COPY.askPlaceholder}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              void ask(question);
            }
          }}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            leadingIcon={MagnifyingGlass}
            loading={loading}
            onClick={() => void ask(question)}
          >
            Preguntar
          </Button>
          <span className="text-xs text-muted">Ctrl + Enter también envía</span>
        </div>
        {examples.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {examples.slice(0, 6).map((item) => (
              <button
                key={item}
                type="button"
                className="badge badge-muted"
                onClick={() => {
                  setQuestion(item);
                  void ask(item);
                }}
              >
                <Sparkle size={12} aria-hidden /> {item}
              </button>
            ))}
          </div>
        )}
      </Panel>

      {loading && (
        <div className="mt-4">
          <Panel>
            <SkeletonBlock rows={3} />
          </Panel>
        </div>
      )}

      {!loading && answer && (
        <div className="mt-4 space-y-4">
          <Panel>
            <PanelHeader
              title="Respuesta"
              description={`Intención: ${INTENT_LABELS[answer.intent] || answer.intent}`}
              actions={
                <Badge tone={answer.certainty === "confirmed" ? "ok" : "warn"}>
                  {answer.certainty === "confirmed"
                    ? "Confirmado en el grafo"
                    : "Contiene relaciones no confirmadas"}
                </Badge>
              }
            />
            <pre
              className="whitespace-pre-wrap text-sm"
              data-testid="company-answer"
            >
              {answer.answer}
            </pre>
            {answer.followups.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {answer.followups.map((followup) => (
                  <button
                    key={followup}
                    type="button"
                    className="badge badge-muted"
                    onClick={() => {
                      setQuestion(followup);
                      void ask(followup);
                    }}
                  >
                    {followup}
                  </button>
                ))}
              </div>
            )}
          </Panel>

          <Panel>
            <PanelHeader title="Evidencia" description="Sin evidencia no hay respuesta" />
            <ul className="space-y-2 text-sm" data-testid="company-evidence">
              {answer.evidence.map((item) => (
                <li key={`${item.kind}-${item.ref}`} className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{item.kind}</Badge>
                  {EVIDENCE_LINKS[item.kind] && item.ref ? (
                    <Link className="underline" to={`${EVIDENCE_LINKS[item.kind]}${item.ref}`}>
                      {item.label || item.ref.slice(0, 8)}
                    </Link>
                  ) : (
                    <span>{item.label || item.ref.slice(0, 8)}</span>
                  )}
                  {typeof item.detail?.status === "string" && (
                    <Badge tone={statusToneFor(item.detail.status as string)}>
                      {statusLabelFor(item.detail.status as string)}
                    </Badge>
                  )}
                </li>
              ))}
              {answer.evidence.length === 0 && (
                <li className="text-muted">La respuesta no tiene evidencia asociada.</li>
              )}
            </ul>
          </Panel>

          <Panel>
            <PanelHeader
              title="Cómo se respondió"
              description={`Proveedor de juicio: ${answer.decision.provider}`}
            />
            {answer.decision.fallback_used && (
              <InfoInline
                message={`Juez no disponible (${answer.decision.reason || "sin señal"}): se usó el router determinista.`}
              />
            )}
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge tone="neutral">
                Contexto: {answer.context_used.tokens_estimate ?? 0} tokens
              </Badge>
              <Badge tone="neutral">{answer.context_used.concepts} conceptos</Badge>
              <Badge tone="neutral">{answer.context_used.mappings} mapeos</Badge>
              <Badge tone="neutral">{answer.context_used.processes} procesos</Badge>
              <Badge tone="neutral">{answer.context_used.systems} sistemas</Badge>
              <Badge tone="neutral">{answer.context_used.memories} memorias</Badge>
              {answer.context_used.truncated && (
                <Badge tone="warn">Contexto recortado por presupuesto</Badge>
              )}
            </div>
          </Panel>
        </div>
      )}
    </CompanyIntelligenceLayout>
  );
}
