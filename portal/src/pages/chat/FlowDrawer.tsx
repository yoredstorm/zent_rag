import { useEffect, useState } from "react";
import { api, type Session } from "../../api";
import { Badge, CodeBlock, Drawer, Progress, Skeleton } from "../../components/ui";
import { fmtCurrency } from "../../lib/format";
import { DecisionSignals, MemoryImpact, type ImpactLoad, type QueryImpact } from "./MemoryImpact";
import { ReplayCompare, type ReplayResult } from "./ReplayCompare";

type Flow = Record<string, unknown>;

function asRecord(value: unknown): Flow {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Flow)
    : {};
}

function asList(value: unknown): Flow[] {
  return Array.isArray(value)
    ? value.filter((item): item is Flow => typeof item === "object" && item !== null)
    : [];
}

function num(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function fmtMs(value: unknown): string {
  const parsed = num(value);
  if (parsed <= 0) return "—";
  return parsed >= 100 ? `${parsed.toFixed(0)} ms` : `${parsed.toFixed(1)} ms`;
}

function fmtText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

const ROUTE_LABEL: Record<string, string> = {
  SQL: "SQL",
  Documentos: "Documentos",
  Directa: "Directa",
  Herramientas: "Herramientas",
  Nodos: "Nodos",
};

const GATE_VERDICT_LABEL: Record<string, string> = {
  approve: "aprobada",
  revise: "revisada",
  revise_exhausted: "aprobada (revisión ya usada)",
  abstain: "abstención",
};

export default function FlowDrawer({
  open,
  onOpenChange,
  flow,
  role,
  queryId,
  question,
  session,
  onFetched,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flow: Flow | null;
  role: "admin" | "customer";
  queryId?: string;
  question?: string;
  session: Session;
  onFetched?: (flow: Flow) => void;
}) {
  const [fetched, setFetched] = useState<Flow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [impact, setImpact] = useState<QueryImpact | null>(null);
  const [impactState, setImpactState] = useState<ImpactLoad>("idle");
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  const [replayError, setReplayError] = useState("");
  const [replayPending, setReplayPending] = useState(false);

  useEffect(() => {
    if (!open || flow || !queryId) return;
    setLoading(true);
    setError("");
    api<{ flow: Flow }>(`/api/v1/rag/queries/${queryId}/flow`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        setFetched(out.flow);
        onFetched?.(out.flow);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "No se pudo cargar el flujo");
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, flow, queryId]);

  useEffect(() => {
    if (!open || !queryId) {
      setImpact(null);
      setImpactState("idle");
      return;
    }
    let cancelled = false;
    setImpact(null);
    setImpactState("loading");
    api<QueryImpact>(`/api/v1/memory/queries/${queryId}/impact`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((body) => {
        if (cancelled) return;
        if (!body?.counts) {
          setImpactState("error");
          return;
        }
        setImpact(body);
        setImpactState("ready");
      })
      .catch(() => {
        if (!cancelled) setImpactState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [open, queryId, session.token, session.organizationId]);

  useEffect(() => {
    setReplay(null);
    setReplayError("");
    setReplayPending(false);
  }, [open, queryId]);

  function runReplay() {
    if (!queryId || replayPending) return;
    setReplayPending(true);
    setReplayError("");
    api<ReplayResult>(`/api/v1/memory/queries/${queryId}/replay`, {
      method: "POST",
      body: JSON.stringify({ question: question ?? "", tools: [] }),
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((body) => {
        if (!body?.comparison?.fields) {
          setReplayError("No se pudo comparar esta respuesta.");
          return;
        }
        setReplay(body);
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "";
        setReplayError(message || "No se pudo reejecutar esta respuesta.");
      })
      .finally(() => setReplayPending(false));
  }

  const active = flow ?? fetched;
  const verdict = asRecord(active?.verdict);
  const decision = asRecord(active?.decision);
  const timings = asRecord(active?.timings);
  const retrieval = asRecord(active?.retrieval);
  const sql = active?.sql ? asRecord(active.sql) : null;
  const generation = active?.generation ? asRecord(active.generation) : null;
  const evidence = active?.evidence ? asRecord(active.evidence) : null;
  const grounding = active?.grounding ? asRecord(active.grounding) : null;
  const jev = asRecord(active?.jev);
  const hasValue = (value: unknown) =>
    value !== null && value !== undefined && value !== "" && value !== "—";
  const sources = asList(active?.sources);
  const steps = asList(active?.steps);
  const fallbacks = Array.isArray(active?.fallbacks) ? (active?.fallbacks as unknown[]) : [];
  const totalMs = num(timings.total_ms) || num(active?.total_ms);
  const confidence = num(decision.confidence);
  const promptTokens = num(generation?.prompt_tokens);
  const completionTokens = num(generation?.completion_tokens);
  const totalTokens = num(generation?.total_tokens) || promptTokens + completionTokens;
  const cost = generation && typeof generation.cost === "number" ? num(generation.cost) : null;
  const costPer1k = cost !== null && totalTokens > 0 ? (cost / totalTokens) * 1000 : null;
  const jevScore = typeof jev.score === "number" ? num(jev.score) : null;
  const jevVerdict = hasValue(jev.verdict)
    ? GATE_VERDICT_LABEL[fmtText(jev.verdict)] ?? fmtText(jev.verdict)
    : "";
  const pricing = asRecord(active?.pricing);
  const currencyInput = num(pricing.input_cost_per_1k);
  const currencyOutput = num(pricing.output_cost_per_1k);
  const hasRetrieval =
    retrieval.used === true || num(retrieval.chunks) > 0 || num(timings.retrieval_ms) > 0;

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Ver flujo"
      description="Cómo Zent resolvió esta respuesta, paso a paso."
    >
      {loading ? <Skeleton className="h-40" /> : null}
      {error ? <p className="text-[13px] text-danger">{error}</p> : null}
      {!loading && !error && active ? (
        <div className="flex flex-col gap-5">
          <div className="rounded-lg border border-border bg-surface p-4">
            <p className="text-[12px] text-faint">Esta respuesta</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="text-h2">
                {decision.evaluated === false
                  ? "Respondió sin decisión (legacy)"
                  : `Decidió ${ROUTE_LABEL[fmtText(verdict.decider)] ?? fmtText(verdict.decider)}`}
              </span>
              <Badge tone={fmtText(verdict.route) === "SQL" ? "info" : "neutral"}>
                {fmtText(verdict.route)}
              </Badge>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] text-muted">
              <span className="tabular-nums">
                Total <span className="mono text-text">{fmtMs(totalMs)}</span>
              </span>
              {decision.evaluated !== false && confidence > 0 ? (
                <span className="tabular-nums">
                  Confianza <span className="mono text-text">{confidence.toFixed(2)}</span>
                </span>
              ) : null}
              {typeof jev.used === "boolean" ? (
                <span className={jev.used ? "text-accent" : "text-faint"}>
                  {jev.used ? "JEV intervino en este run" : "JEV no intervino en este run"}
                </span>
              ) : decision.jev_used ? (
                <span className="text-accent">JEV ejecutó la decisión</span>
              ) : null}
              {decision.fallback_used ? <span className="text-warn">Usó plan de respaldo</span> : null}
            </div>
            <div className="mt-4">
              <DecisionSignals
                flow={active}
                used={impact?.used ?? []}
                impactReady={impactState === "ready"}
              />
            </div>
          </div>

          {steps.length > 0 ? (
            <div>
              <p className="eyebrow mb-2">Pasos y tiempos</p>
              <ol className="flex flex-col gap-1.5">
                {steps.map((step, index) => (
                  <li
                    key={`${fmtText(step.name)}-${index}`}
                    className="flex flex-wrap items-center gap-2 rounded-sm border border-border-soft px-2.5 py-2 text-[12.5px]"
                    data-state={step.status === "warn" ? "warning" : "ready"}
                  >
                    <span className="mono w-5 text-[10px] text-faint">{index + 1}</span>
                    <span className="min-w-0 flex-1 font-medium text-text">
                      {fmtText(step.name)}
                    </span>
                    {step.detail ? (
                      <span className="min-w-0 truncate text-[11px] text-muted">
                        {fmtText(step.detail)}
                      </span>
                    ) : null}
                    <span className="mono tabular-nums text-[11px] text-faint">
                      {fmtMs(step.ms)}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          <div>
            <p className="eyebrow mb-2">Detalle</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
              {hasValue(decision.provider) ? (
                <div>
                  <dt className="text-faint">Proveedor</dt>
                  <dd className="text-text">{fmtText(decision.provider)}</dd>
                </div>
              ) : null}
              {hasValue(decision.capability) ? (
                <div>
                  <dt className="text-faint">Capability</dt>
                  <dd className="text-text">{fmtText(decision.capability)}</dd>
                </div>
              ) : null}
              {hasValue(decision.mode) ? (
                <div>
                  <dt className="text-faint">Modo</dt>
                  <dd className="text-text">{fmtText(decision.mode)}</dd>
                </div>
              ) : null}
              {num(decision.ms) > 0 ? (
                <div>
                  <dt className="text-faint">Decisión</dt>
                  <dd className="text-text">{fmtMs(decision.ms)}</dd>
                </div>
              ) : null}
              {hasRetrieval ? (
                <div>
                  <dt className="text-faint">Búsqueda</dt>
                  <dd className="text-text">
                    {fmtMs(timings.retrieval_ms)} · {num(retrieval.chunks)} fragmentos
                  </dd>
                </div>
              ) : null}
              {num(retrieval.top_score) > 0 ? (
                <div>
                  <dt className="text-faint">Mejor score</dt>
                  <dd className="text-text">{fmtText(retrieval.top_score)}</dd>
                </div>
              ) : null}
              {num(timings.embedding_ms) > 0 ? (
                <div>
                  <dt className="text-faint">Embedding</dt>
                  <dd className="text-text">{fmtMs(timings.embedding_ms)}</dd>
                </div>
              ) : null}
              {num(timings.generation_ms) > 0 || totalTokens > 0 ? (
                <div>
                  <dt className="text-faint">Respuesta LLM</dt>
                  <dd className="text-text">
                    {num(timings.generation_ms) > 0 ? fmtMs(timings.generation_ms) : "—"}
                  </dd>
                </div>
              ) : null}
              {hasValue(generation?.model) ? (
                <div>
                  <dt className="text-faint">Modelo</dt>
                  <dd className="text-text">{fmtText(generation?.model)}</dd>
                </div>
              ) : null}
              {totalTokens > 0 ? (
                <div>
                  <dt className="text-faint">Tokens</dt>
                  <dd className="text-text">
                    {promptTokens > 0 || completionTokens > 0
                      ? `${promptTokens} / ${completionTokens}`
                      : `${totalTokens}`}
                  </dd>
                </div>
              ) : null}
              {cost !== null && cost > 0 ? (
                <div>
                  <dt className="text-faint">Costo</dt>
                  <dd className="text-text">{fmtCurrency(cost, 6)}</dd>
                </div>
              ) : null}
              {costPer1k !== null && costPer1k > 0 ? (
                <div>
                  <dt className="text-faint">Costo / 1k tokens</dt>
                  <dd className="text-text">{fmtCurrency(costPer1k, 6)}</dd>
                </div>
              ) : null}
              {currencyInput > 0 || currencyOutput > 0 ? (
                <div className="col-span-2">
                  <dt className="text-faint">Precio del modelo (entrada / salida por 1k)</dt>
                  <dd className="text-text">
                    {fmtCurrency(currencyInput, 6)} / {fmtCurrency(currencyOutput, 6)}
                  </dd>
                </div>
              ) : null}
              {jevScore !== null ? (
                <div>
                  <dt className="text-faint">Score JEV</dt>
                  <dd className="text-text">
                    {jevScore.toFixed(2)}
                    {jevVerdict ? ` · ${jevVerdict}` : ""}
                  </dd>
                </div>
              ) : null}
              {evidence ? (
                <div>
                  <dt className="text-faint">Evidencia</dt>
                  <dd className="text-text">
                    {fmtText(evidence.score)} · {evidence.sufficient ? "suficiente" : "insuficiente"}
                  </dd>
                </div>
              ) : null}
              {grounding ? (
                <div>
                  <dt className="text-faint">Verificación</dt>
                  <dd className="text-text">
                    {grounding.grounded ? "respaldada" : "sin respaldo"} · {fmtText(grounding.score)}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>

          {sql && role === "admin" ? (
            <div>
              <p className="eyebrow mb-2">SQL ejecutado</p>
              <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
                <span className="tabular-nums">
                  Filas <span className="mono text-text">{num(sql.rows)}</span>
                </span>
                <span className="tabular-nums">
                  Tiempo <span className="mono text-text">{fmtMs(sql.ms)}</span>
                </span>
                {Array.isArray(sql.tables) && sql.tables.length > 0 ? (
                  <span>Tablas: {sql.tables.join(", ")}</span>
                ) : null}
              </div>
              <CodeBlock code={String(sql.query ?? "")} language="sql" maxHeight={240} />
            </div>
          ) : null}

          {sources.length > 0 ? (
            <div>
              <p className="eyebrow mb-2">Fuentes usadas</p>
              <ul className="flex flex-col gap-2">
                {sources.map((source, index) => (
                  <li key={`${fmtText(source.document_id)}-${index}`}>
                    <div className="flex items-center justify-between gap-2 text-[12.5px]">
                      <span className="min-w-0 truncate text-text">
                        {fmtText(source.title)}
                      </span>
                      <span className="mono shrink-0 text-[11px] text-faint">
                        {(num(source.score) * 100).toFixed(0)}%
                      </span>
                    </div>
                    <Progress value={Math.round(num(source.score) * 100)} className="mt-1" />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {fallbacks.length > 0 ? (
            <div>
              <p className="eyebrow mb-2">Respaldos activados</p>
              <div className="flex flex-wrap gap-1">
                {fallbacks.map((item, index) => (
                  <Badge key={`${String(item)}-${index}`} tone="warn">
                    {String(item)}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          <MemoryImpact state={impactState} impact={impact} />
          {queryId ? (
            <ReplayCompare
              result={replay}
              error={replayError}
              pending={replayPending}
              onReplay={runReplay}
            />
          ) : null}
        </div>
      ) : null}
    </Drawer>
  );
}
