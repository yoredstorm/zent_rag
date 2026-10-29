// =============================================================================
// KnowledgeImportWizard — Elegir · Incorporar · Comprobar
// =============================================================================
// Un solo recorrido para archivos. La verdad durable sigue en Sources,
// Knowledge Sessions y el motor canónico; este componente solo la representa.
// =============================================================================
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ChatCircleDots,
  CheckCircle,
  Database,
  FileText,
  FolderSimple,
  Globe,
  Plugs,
  Plus,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { FileDropzone } from "../FileDropzone";
import {
  SelectedFilesList,
  UploadResultsList,
} from "../UploadQueueList";
import {
  Button,
  ButtonLink,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from "../ui";
import {
  mergeSelectedFiles,
  uploadErrorMessage,
  type UploadItem,
} from "../../lib/uploadQueue";
import {
  startLearningSession,
  sealLearningSession,
} from "../../lib/knowledgeSessions";
import { uploadSourceFile } from "../../lib/sourceUploads";
import { useLearningSession } from "../knowledgeSession/useLearningSession";
import { sourceReadiness } from "../../pages/knowledge/sourceState";
import {
  batchProgressLabel,
  canAskBatch,
  initialWizardBatch,
  wizardBatchReducer,
} from "./wizardMachine";

const MAX_FILES = 20;

type Step = "choose" | "files" | "connect" | "check";

type ConnectorChoice = {
  kind: "database" | "website" | "api" | "drive";
  label: string;
  description: string;
  icon: typeof Database;
};

const CONNECTORS: ConnectorChoice[] = [
  {
    kind: "database",
    label: "Base de datos",
    description: "ERP o base empresarial de solo lectura.",
    icon: Database,
  },
  {
    kind: "drive",
    label: "Google Drive",
    description: "Una carpeta compartida que ZENT pueda leer.",
    icon: FolderSimple,
  },
  {
    kind: "website",
    label: "Sitio web",
    description: "Páginas públicas que ZENT debe entender.",
    icon: Globe,
  },
  {
    kind: "api",
    label: "API",
    description: "Un sistema externo con acceso autorizado.",
    icon: Plugs,
  },
];

function formatStatus(status: string): string {
  if (status === "completed" || status === "available") {
    return "Listo para consultar";
  }
  if (status === "learning") return "Procesando";
  if (status === "failed") return "Necesita atención";
  if (status === "pending") return "Recibido";
  return sourceReadiness(status).label;
}

export function KnowledgeImportWizard({
  open,
  onClose,
  onMinimize,
  onSession,
  initialSessionId,
  initialCorpusId,
}: {
  open: boolean;
  onClose: () => void;
  onMinimize?: (sessionId: string) => void;
  onSession?: (sessionId: string) => void;
  initialSessionId?: string | null;
  initialCorpusId?: string | null;
}) {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(initialSessionId ? "check" : "choose");
  const [files, setFiles] = useState<File[]>([]);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [batch, dispatchBatch] = useReducer(
    wizardBatchReducer,
    initialWizardBatch,
  );
  const [sessionId, setSessionId] = useState<string | null>(
    initialSessionId ?? null,
  );
  const [corpusId, setCorpusId] = useState<string | null>(
    initialCorpusId ?? null,
  );
  const [corpora, setCorpora] = useState<
    { id: string; name: string; slug: string }[]
  >([]);
  const [corpusName, setCorpusName] = useState("Principal");
  const [readySourceIds, setReadySourceIds] = useState<string[]>([]);
  const [readyInfo, setReadyInfo] = useState({
    total: 0,
    ready: 0,
    failed: 0,
  });
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [retrying, setRetrying] = useState("");
  const [selectedConnector, setSelectedConnector] = useState<
    ConnectorChoice["kind"] | null
  >(null);
  const uploadingRef = useRef(false);
  const hydratedSessionRef = useRef<string | null>(initialSessionId ?? null);

  const createdItems = useMemo(
    () => items.filter((item) => item.status === "created"),
    [items],
  );
  const failedItems = useMemo(
    () =>
      items.filter(
        (item) =>
          item.status === "error" ||
          item.status === "rejected" ||
          item.status === "duplicate",
      ),
    [items],
  );
  const askableCount =
    readySourceIds.length > 0
      ? readySourceIds.length
      : createdItems.filter((item) => item.source_id).length;
  const askEnabled =
    !uploading &&
    askableCount > 0 &&
    (readySourceIds.length > 0 || canAskBatch(batch));

  useEffect(() => {
    const next = initialSessionId ?? null;
    if (!next || next === hydratedSessionRef.current) return;
    // Un cambio de URL durante una transferencia no mueve el paso ni pisa el
    // lote activo. Solo una reapertura explícita fuera de transferencia hidrata.
    if (uploadingRef.current) return;
    hydratedSessionRef.current = next;
    setSessionId(next);
    setStep("check");
  }, [initialSessionId]);

  useEffect(() => {
    if (initialCorpusId) setCorpusId(initialCorpusId);
  }, [initialCorpusId]);

  useEffect(() => {
    if (!open || !session?.token) return;
    let cancelled = false;
    void api<{ corpora: { id: string; name: string; slug: string }[] }>(
      "/api/v1/knowledge/workspaces",
      { token: session.token, organizationId: session.organizationId },
    )
      .then((data) => {
        if (cancelled) return;
        const corpora = data.corpora ?? [];
        setCorpora(corpora);
        const selected =
          corpora.find((item) => item.id === corpusId) ??
          corpora.find((item) => item.slug === "principal") ??
          corpora[0];
        setCorpusName(selected?.name ?? "Principal");
        setCorpusId((current) => current ?? selected?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) setCorpusName("Principal");
      });
    return () => {
      cancelled = true;
    };
  }, [open, session?.token, session?.organizationId, corpusId]);

  useEffect(() => {
    if (sessionId) onSession?.(sessionId);
    // El callback es de presentación; solo importa cuando cambia la sesión.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const handleSessionState = useCallback(
    (info: { readyIds: string[]; total: number; ready: number; failed: number }) => {
      setReadySourceIds(info.readyIds);
      setReadyInfo({ total: info.total, ready: info.ready, failed: info.failed });
      if (sessionId) dispatchBatch({ type: "session", sessionId });
      dispatchBatch({
        type: "settled",
        ready: info.ready,
        failed: info.failed,
        total: info.total,
      });
    },
    [sessionId],
  );

  if (!open) return null;

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    if (incoming.length === 0) return;
    setError("");
    setFiles((prev) => mergeSelectedFiles(prev, incoming).slice(0, MAX_FILES));
    setItems([]);
  }

  async function uploadAll() {
    if (!session?.token || files.length === 0) return;
    uploadingRef.current = true;
    setUploading(true);
    setError("");
    setMsg("");
    setItems([]);
    setReadySourceIds([]);
    setReadyInfo({ total: 0, ready: 0, failed: 0 });
    dispatchBatch({ type: "start", total: files.length });
    if (sessionId) dispatchBatch({ type: "session", sessionId });
    const auth = { token: session.token, organizationId: session.organizationId };
    const results: UploadItem[] = [];
    let activeSession: string | null = sessionId;
    let activeCorpus: string | null = corpusId;
    let created = 0;
    let failed = 0;
    try {
      if (!activeSession) {
        try {
          const learningStart = await startLearningSession({
            title:
              files.length === 1
                ? `Aprendiendo ${files[0].name}`
                : `Aprendiendo ${files.length} fuentes`,
            origin: "upload",
          });
          activeSession = learningStart.session_id;
          setSessionId(activeSession);
          dispatchBatch({ type: "session", sessionId: activeSession });
        } catch {
          // El upload-batch puede abrir la sesión; se captura su session_id.
        }
      }
      for (const file of files) {
        try {
          const uploaded = await uploadSourceFile(file, auth, {
            corpusId: activeCorpus ?? undefined,
            sessionId: activeSession ?? undefined,
          });
          if (uploaded.sessionId) {
            activeSession = uploaded.sessionId;
            setSessionId(uploaded.sessionId);
            dispatchBatch({ type: "session", sessionId: uploaded.sessionId });
          }
          if (uploaded.corpusId) {
            activeCorpus = uploaded.corpusId;
            setCorpusId(uploaded.corpusId);
          }
          results.push(uploaded.item);
          if (uploaded.item.status === "created") created += 1;
          else if (
            uploaded.item.status === "error" ||
            uploaded.item.status === "rejected"
          ) {
            failed += 1;
          }
          dispatchBatch({
            type: "uploaded",
            ok: uploaded.item.status === "created",
          });
        } catch (err) {
          failed += 1;
          results.push({
            filename: file.name,
            status: "error",
            error: uploadErrorMessage(err),
          });
          dispatchBatch({ type: "uploaded", ok: false });
        }
        setItems([...results]);
      }
      if (created > 0) {
        setMsg(
          created === 1
            ? "1 archivo recibido. El procesamiento sigue."
            : `${created} archivos recibidos. El procesamiento sigue.`,
        );
      }
      if (failed > 0) {
        setError(
          failed === 1
            ? "1 archivo no se pudo subir. Revisa el detalle y reintenta."
            : `${failed} archivos no se pudieron subir. Revisa el detalle.`,
        );
      }
      if (activeSession) {
        try {
          await sealLearningSession(activeSession);
        } catch {
          // El backend cierra la sesión tras el margen de seguridad.
        }
        setStep("check");
      } else if (created > 0) {
        setStep("check");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al subir");
    } finally {
      uploadingRef.current = false;
      setUploading(false);
    }
  }

  async function retry(item: UploadItem) {
    if (!session?.token) return;
    const file = files.find((candidate) => candidate.name === item.filename);
    if (!file) return;
    setRetrying(item.filename);
    setError("");
    try {
      const uploaded = await uploadSourceFile(
        file,
        { token: session.token, organizationId: session.organizationId },
        {
          corpusId: corpusId ?? undefined,
          force: true,
          sessionId: sessionId ?? undefined,
        },
      );
      if (uploaded.sessionId) setSessionId(uploaded.sessionId);
      if (uploaded.corpusId) setCorpusId(uploaded.corpusId);
      setItems((prev) =>
        prev.map((candidate) =>
          candidate.filename === item.filename ? uploaded.item : candidate,
        ),
      );
      if (uploaded.item.status === "created") {
        setMsg("Copia recibida. El procesamiento sigue.");
      }
    } catch (err) {
      setError(uploadErrorMessage(err));
    } finally {
      setRetrying("");
    }
  }

  function askFirstQuestion() {
    const params = new URLSearchParams();
    if (corpusId) params.set("corpus", corpusId);
    const askableIds =
      readySourceIds.length > 0
        ? readySourceIds
        : createdItems
            .map((item) => item.source_id)
            .filter((id): id is string => Boolean(id));
    if (askableIds.length > 0) params.set("source_ids", askableIds.join(","));
    if (question.trim()) params.set("q", question.trim());
    navigate(`/knowledge/ask?${params.toString()}`);
  }

  function startNewBatch() {
    // Una sesión sellada no se reutiliza. El lote nuevo abre su propia sesión
    // cuando se confirma la primera transferencia.
    dispatchBatch({ type: "reset" });
    setSessionId(null);
    setFiles([]);
    setItems([]);
    setReadySourceIds([]);
    setReadyInfo({ total: 0, ready: 0, failed: 0 });
    setQuestion("");
    setError("");
    setMsg("");
    setStep("files");
    onSession?.("");
  }

  return (
    <Panel data-testid="knowledge-import-wizard">
      <PanelHeader
        title="Añadir información"
        description="Elegir, incorporar y comprobar. Sin conceptos de RAG."
        actions={
          <span className="flex items-center gap-1">
            {onMinimize && sessionId ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onMinimize(sessionId)}
              >
                Minimizar
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              aria-label="Cerrar asistente de incorporación"
              onClick={onClose}
            >
              <X size={15} aria-hidden />
            </Button>
          </span>
        }
      />

      <div className="panel-body flex flex-col gap-4">
        <ol
          className="grid grid-cols-3 gap-2"
          aria-label="Etapas de incorporación"
        >
          {[
            ["1", "Elegir", "Archivo o sistema", "choose"],
            ["2", "Incorporar", "Transferir y leer", "files"],
            ["3", "Comprobar", "Ver y preguntar", "check"],
          ].map(([number, label, hint, value]) => {
            const current =
              (step === "choose" && value === "choose") ||
              ((step === "files" || step === "connect") && value === "files") ||
              (step === "check" && value === "check");
            return (
              <li
                key={value}
                aria-current={current ? "step" : undefined}
                className={`rounded-md border px-3 py-2 text-xs ${
                  current
                    ? "border-accent bg-accent/10 text-text"
                    : "border-border text-muted"
                }`}
              >
                <strong>
                  {number}. {label}
                </strong>
                <span className="mt-1 block text-[11px] text-faint">{hint}</span>
              </li>
            );
          })}
        </ol>

        {error ? (
          <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
            {error}
          </p>
        ) : null}
        {msg ? (
          <p className="rounded-md border border-ok/30 bg-ok-soft px-3 py-2 text-xs text-ok">
            {msg}
          </p>
        ) : null}

        {step === "choose" ? (
          <div className="grid gap-2 sm:grid-cols-3" data-testid="wizard-choose">
            <button
              type="button"
              className="flex items-start gap-2.5 rounded-md border border-border bg-soft px-3 py-3 text-left transition-colors hover:border-border-strong"
              onClick={() => setStep("files")}
            >
              <FileText size={17} className="mt-0.5 shrink-0 text-accent" aria-hidden />
              <span>
                <span className="block text-[13px] font-medium text-text">
                  Subir documentos
                </span>
                <span className="mt-1 block text-[11px] leading-relaxed text-faint">
                  PDF, DOCX, TXT, CSV o Excel. Hasta 25 MB por archivo.
                </span>
              </span>
            </button>
            <button
              type="button"
              className="flex items-start gap-2.5 rounded-md border border-border bg-soft px-3 py-3 text-left transition-colors hover:border-border-strong"
              onClick={() => setStep("connect")}
            >
              <Plugs size={17} className="mt-0.5 shrink-0 text-accent" aria-hidden />
              <span>
                <span className="block text-[13px] font-medium text-text">
                  Conectar un sistema
                </span>
                <span className="mt-1 block text-[11px] leading-relaxed text-faint">
                  Base de datos, Drive, web o API existentes.
                </span>
              </span>
            </button>
            <button
              type="button"
              className="flex items-start gap-2.5 rounded-md border border-border bg-soft px-3 py-3 text-left transition-colors hover:border-border-strong"
              onClick={() => {
                setError("");
                setMsg("Tus fuentes existentes están abajo.");
                setStep("check");
              }}
            >
              <FolderSimple size={17} className="mt-0.5 shrink-0 text-accent" aria-hidden />
              <span>
                <span className="block text-[13px] font-medium text-text">
                  Usar una fuente existente
                </span>
                <span className="mt-1 block text-[11px] leading-relaxed text-faint">
                  Revisa lo que ya está cargado.
                </span>
              </span>
            </button>
          </div>
        ) : null}

        {step === "connect" ? (
          <div className="flex flex-col gap-3" data-testid="wizard-connect">
            <p className="text-sm text-muted">
              La conexión se completa en el asistente especializado. ZENT pedirá
              acceso de solo lectura y verificará la conexión antes de usarla.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {CONNECTORS.map((connector) => {
                const Icon = connector.icon;
                return (
                  <button
                    key={connector.kind}
                    type="button"
                    onClick={() => setSelectedConnector(connector.kind)}
                    className={`flex items-start gap-2 rounded-md border px-3 py-2 text-left text-xs ${
                      selectedConnector === connector.kind
                        ? "border-accent bg-accent/10"
                        : "border-border bg-soft hover:border-border-strong"
                    }`}
                  >
                    <Icon size={15} className="mt-0.5 shrink-0 text-accent" aria-hidden />
                    <span>
                      <span className="block font-medium text-text">
                        {connector.label}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-faint">
                        {connector.description}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                disabled={!selectedConnector}
                onClick={() => {
                  if (!selectedConnector) return;
                  navigate(`/knowledge/add?kind=${selectedConnector}`);
                }}
              >
                Continuar conexión
              </Button>
              <Button
                variant="ghost"
                leadingIcon={ArrowLeft}
                onClick={() => setStep("choose")}
              >
                Volver
              </Button>
            </div>
          </div>
        ) : null}

        {step === "files" ? (
          <div className="flex flex-col gap-3" data-testid="wizard-files">
            <div className="rounded-md border border-border bg-soft p-3">
              <p className="text-sm text-muted">
                Se incorporan a{" "}
                <strong className="text-text">{corpusName}</strong>. El destino se
                valida en el servidor; puedes cambiarlo después en Fuentes.
              </p>
              {corpora.length > 1 ? (
                <label className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>Guardar en</span>
                  <Select
                    aria-label="Corpus de destino"
                    value={corpusId ?? ""}
                    onChange={(event) => {
                      const next = corpora.find(
                        (item) => item.id === event.target.value,
                      );
                      setCorpusId(next?.id ?? null);
                      setCorpusName(next?.name ?? "Principal");
                    }}
                    className="min-h-8 w-[220px]"
                  >
                    {corpora.map((corpus) => (
                      <option key={corpus.id} value={corpus.id}>
                        {corpus.name}
                      </option>
                    ))}
                  </Select>
                </label>
              ) : null}
            </div>
            <FileDropzone
              onFiles={addFiles}
              inputTestId="wizard-source-files"
              dropzoneTestId="wizard-dropzone"
            />
            <SelectedFilesList
              files={files}
              onRemove={(file) =>
                setFiles((prev) => prev.filter((candidate) => candidate !== file))
              }
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                leadingIcon={Plus}
                loading={uploading}
                disabled={uploading || files.length === 0}
                onClick={() => void uploadAll()}
              >
                {files.length > 1
                  ? `Incorporar ${files.length} archivos`
                  : "Incorporar archivo"}
              </Button>
              <Button
                variant="ghost"
                leadingIcon={ArrowLeft}
                onClick={() => setStep("choose")}
              >
                Volver
              </Button>
            </div>
            {uploading ? (
              <div
                className="rounded-lg border border-border bg-soft p-3"
                role="status"
                aria-live="polite"
                data-testid="wizard-upload-progress"
              >
                <div className="flex items-center justify-between gap-2 text-sm">
                  <strong>Enviando archivos</strong>
                  <span className="tabular-nums">
                    {batch.confirmed + batch.failed} de {batch.total}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted">
                  {batchProgressLabel(batch)}. El procesamiento se muestra en el
                  siguiente paso, con eventos reales.
                </p>
              </div>
            ) : null}
            <UploadResultsList
              items={items}
              retrying={retrying}
              onRetry={(item) => void retry(item)}
            />
          </div>
        ) : null}

        {step === "check" ? (
          <div className="flex flex-col gap-4" data-testid="wizard-check">
            {sessionId ? (
              <WizardSessionCheck
                sessionId={sessionId}
                onState={handleSessionState}
                onOpenSession={() =>
                  navigate(`/knowledge/sessions/${sessionId}`)
                }
              />
            ) : (
              <div className="rounded-md border border-border bg-soft p-3">
                <p className="text-sm text-text">
                  {createdItems.length > 0
                    ? "Los archivos se recibieron. Abre Fuentes para ver su estado."
                    : "Todavía no hay archivos en este recorrido."}
                </p>
                {failedItems.length > 0 ? (
                  <p className="mt-1 text-xs text-warn">
                    {failedItems.length} archivo(s) necesitan revisión.
                  </p>
                ) : null}
                <ButtonLink
                  to="/knowledge/sources"
                  variant="secondary"
                  className="mt-3"
                >
                  Ver fuentes
                </ButtonLink>
              </div>
            )}

            {items.length > 0 ? (
              <UploadResultsList
                items={items}
                retrying={retrying}
                onRetry={(item) => void retry(item)}
              />
            ) : null}

            {createdItems.length > 0 || sessionId ? (
              <div className="rounded-md border border-border p-3">
                <p className="text-sm font-medium text-text">
                  Haz tu primera pregunta
                </p>
                <p className="mt-1 text-xs text-muted">
                  ZENT responderá solo con las fuentes listas de esta
                  incorporación.
                </p>
                {readyInfo.total > 0 && readyInfo.ready < readyInfo.total ? (
                  <p className="mt-1 text-xs text-warn" role="status">
                    {readyInfo.ready} de {readyInfo.total} fuentes listas.
                    {readyInfo.failed > 0
                      ? ` ${readyInfo.failed} necesitan revisión.`
                      : " El resto sigue procesándose."}
                  </p>
                ) : null}
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  <Textarea
                    aria-label="Primera pregunta"
                    rows={2}
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="¿Qué información contiene?"
                  />
                  <Button
                    variant="primary"
                    leadingIcon={ChatCircleDots}
                    disabled={!askEnabled}
                    title={
                      askEnabled
                        ? undefined
                        : "Esperando fuentes listas para consultar"
                    }
                    onClick={askFirstQuestion}
                  >
                    {askEnabled
                      ? `Preguntar sobre ${askableCount} fuente${
                          askableCount === 1 ? "" : "s"
                        }`
                      : "Esperando fuentes listas"}
                  </Button>
                </div>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                leadingIcon={ArrowLeft}
                onClick={startNewBatch}
              >
                Añadir más archivos
              </Button>
              <Button variant="ghost" onClick={onClose}>
                Cerrar
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

function WizardSessionCheck({
  sessionId,
  onOpenSession,
  onState,
}: {
  sessionId: string;
  onOpenSession: () => void;
  onState?: (info: {
    readyIds: string[];
    total: number;
    ready: number;
    failed: number;
  }) => void;
}) {
  const { detail, loading, error, connected, stage } = useLearningSession(
    sessionId,
    { includeGraph: false },
  );
  const sources = useMemo(() => detail?.sources ?? [], [detail]);
  const total = detail?.source_count ?? 0;
  const readyIds = useMemo(
    () =>
      sources
        .filter((source) =>
          ["completed", "available", "indexed"].includes(source.status),
        )
        .map((source) => source.id),
    [sources],
  );
  const ready = Math.min(total, readyIds.length);

  useEffect(() => {
    if (!detail) return;
    onState?.({
      readyIds,
      total,
      ready,
      failed: detail.failed_sources ?? 0,
    });
  }, [detail, readyIds, total, ready, onState]);

  return (
    <div
      className="rounded-md border border-border bg-soft p-3"
      data-testid="wizard-session-check"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-text">
          {detail?.is_available
            ? "Disponible para consultar"
            : "Procesando la información"}
        </p>
        <span className="text-[11px] text-faint">
          {connected ? "En vivo" : "Sincronizando"}
        </span>
      </div>
      {loading && !detail ? (
        <p className="mt-2 text-xs text-muted" role="status">
          Cargando la sesión real…
        </p>
      ) : error ? (
        <p className="mt-2 flex items-start gap-1 text-xs text-warn">
          <WarningCircle size={13} className="mt-0.5 shrink-0" aria-hidden />
          {error}. La fuente puede seguir procesándose; abre el detalle.
        </p>
      ) : detail ? (
        <>
          <p className="mt-2 text-xs text-muted">
            {ready} de {total} fuentes listas
            {detail.failed_sources > 0
              ? ` · ${detail.failed_sources} necesitan revisión`
              : ""}
            {stage ? ` · ${detail.stage_label || stage}` : ""}
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {sources.map((source) => (
              <li
                key={source.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-border-soft bg-surface px-2 py-1.5 text-xs"
              >
                <span className="min-w-0 flex-1 truncate text-text">
                  {source.name}
                </span>
                <span className="text-faint">{formatStatus(source.status)}</span>
                {source.error ? (
                  <span className="text-danger">{source.error}</span>
                ) : null}
              </li>
            ))}
          </ul>
          {detail.is_available ? (
            <p className="mt-2 flex items-center gap-1 text-[11px] text-ok">
              <CheckCircle size={12} aria-hidden />
              Ya puedes preguntar. La disponibilidad no equivale a validación
              para tareas críticas.
            </p>
          ) : null}
        </>
      ) : null}
      <Button
        variant="ghost"
        size="sm"
        className="mt-2"
        onClick={onOpenSession}
        leadingIcon={ArrowRight}
      >
        Ver sesión completa
      </Button>
    </div>
  );
}
