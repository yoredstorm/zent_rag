import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import { useAuth } from "../../../auth";
import { ErrorInline, PageHeader } from "../../../components/ui";
import { WarningInline } from "../../../components/ui/states";
import { KnowledgeLayout } from "../../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../../lib/knowledgeNav";
import { Stepper } from "../../../components/Stepper";
import {
  MAX_UPLOAD_MB,
  isOversized,
  mergeSelectedFiles,
  uploadErrorMessage,
  type UploadItem,
} from "../../../lib/uploadQueue";
import { AnalysisProgressStep } from "./AnalysisProgressStep";
import { ApiStep } from "./ApiStep";
import { DatabaseConnectionStep } from "./DatabaseConnectionStep";
import { DriveStep } from "./DriveStep";
import { FileUploadStep } from "./FileUploadStep";
import { QuestionValidationStep } from "./QuestionValidationStep";
import { ReadinessStep } from "./ReadinessStep";
import { SourceTypeStep } from "./SourceTypeStep";
import { UnderstandingReviewStep } from "./UnderstandingReviewStep";
import { WebsiteStep } from "./WebsiteStep";
import {
  API,
  FLOW_QUESTION_HEADING,
  WIZARD_STEPS,
  canContinueAnalyze,
  type OnboardingKind,
  type OnboardingSession,
  type ProgressPayload,
  type ReadinessPayload,
  type Suggestion,
  type Understanding,
  type WizardStep,
} from "./types";

export default function OnboardingWizardPage() {
  const { session } = useAuth();
  const { sessionId } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [current, setCurrent] = useState<OnboardingSession | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [progress, setProgress] = useState<ProgressPayload | null>(null);
  const [tech, setTech] = useState(false);
  const [understanding, setUnderstanding] = useState<Understanding>({});
  const [questions, setQuestions] = useState<Array<{ id: string; text: string }>>([]);
  const [answer, setAnswer] = useState<Record<string, unknown> | null>(null);
  const [askError, setAskError] = useState("");
  const [activeQuestion, setActiveQuestion] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<ReadinessPayload | null>(null);
  const [folders, setFolders] = useState<Array<{ id: string; name: string }>>([]);
  const [authUrl, setAuthorizationUrl] = useState("");
  const [webPreview, setWebPreview] = useState<{ url?: string; host?: string; pages_detected?: number }>();
  const [webUrl, setWebUrl] = useState("");
  const [dbResult, setDbResult] = useState<OnboardingSession["connection"]>();
  const [apiResult, setApiResult] = useState<OnboardingSession["connection"]>();
  const [uiStep, setUiStep] = useState<WizardStep>("choose");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [retrying, setRetrying] = useState("");

  const load = useCallback(
    async (id: string) => {
      if (!session) return;
      const data = await api<OnboardingSession>(`${API}/sessions/${id}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setCurrent(data);
      const step: WizardStep =
        data.step === "confirm"
          ? "review"
          : data.kind && data.step === "choose"
            ? "connect"
            : data.step;
      setUiStep(step);
      if (step !== "choose" && step !== "connect") {
        try {
          const prog = await api<ProgressPayload>(`${API}/sessions/${id}/progress`, {
            token: session.token,
            organizationId: session.organizationId,
          });
          setProgress(prog);
          setCurrent(prog.session);
        } catch {
          /* progress optional on resume */
        }
        try {
          const und = await api<Understanding>(`${API}/sessions/${id}/understanding`, {
            token: session.token,
            organizationId: session.organizationId,
          });
          setUnderstanding(und);
        } catch {
          /* understanding optional */
        }
      }
      if (step === "test") {
        const pack = await api<{ questions: Array<{ id: string; text: string }> }>(
          `${API}/sessions/${id}/questions`,
          { token: session.token, organizationId: session.organizationId }
        );
        setQuestions(pack.questions || []);
      }
      if (step === "ready") {
        const ready = await api<ReadinessPayload>(`${API}/sessions/${id}/readiness`, {
          token: session.token,
          organizationId: session.organizationId,
        });
        setReadiness(ready);
      }
      return data;
    },
    [session]
  );

  useEffect(() => {
    if (sessionId && session) {
      load(sessionId).catch((e) => setError(String(e)));
    }
  }, [sessionId, session, load]);

  useEffect(() => {
    if (uiStep !== "analyze" || !current) return;
    if (["REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION"].includes(current.status)) return;
    if (!current.kb_source_id && !current.connector_id) return;
    void runAnalyze();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uiStep, current?.id]);

  useEffect(() => {
    const gdrive = search.get("gdrive");
    const connectorId = search.get("connector_id");
    if (gdrive === "ok" && sessionId && session && connectorId) {
      api<{ folders: Array<{ id: string; name: string }> }>(
        `${API}/sessions/${sessionId}/connect/drive/folders`,
        { token: session.token, organizationId: session.organizationId }
      )
        .then((data) => setFolders(data.folders || []))
        .catch((e) => setError(String(e)));
    }
  }, [search, sessionId, session]);

  async function startKind(kind: OnboardingKind) {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const created = await api<OnboardingSession>(`${API}/sessions`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ kind }),
      });
      navigate(`/knowledge/add/${created.id}`);
      setCurrent(created);
      setUiStep("connect");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function connectDatabase(body: Record<string, unknown>) {
    if (!session || !current) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<OnboardingSession>(`${API}/sessions/${current.id}/connect/database`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(body),
      });
      setCurrent(data);
      setDbResult(data.connection);
      if (data.connection?.ok) setUiStep("analyze");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  function addUploadFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    if (incoming.length === 0) return;
    const oversized = incoming.filter(isOversized);
    if (oversized.length > 0) {
      setError(
        oversized.length === 1
          ? `${oversized[0].name} supera el máximo por archivo (${MAX_UPLOAD_MB} MB).`
          : `${oversized.length} archivos superan el máximo por archivo (${MAX_UPLOAD_MB} MB).`,
      );
    } else {
      setError("");
    }
    const valid = incoming.filter((file) => !isOversized(file));
    if (valid.length === 0) return;
    setUploadItems([]);
    setUploadFiles((prev) => mergeSelectedFiles(prev, valid));
  }

  async function uploadSingle(file: File, force: boolean): Promise<UploadItem> {
    if (!session || !current) {
      return { filename: file.name, status: "error", error: "Sesión no disponible" };
    }
    const form = new FormData();
    form.append("file", file);
    const query = force ? "?force=true" : "";
    const data = await api<OnboardingSession & { upload?: UploadItem }>(
      `${API}/sessions/${current.id}/connect/upload${query}`,
      {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: form,
      },
    );
    setCurrent(data);
    return (
      data.upload ?? {
        filename: file.name,
        status: "error",
        error: "El servidor no devolvió resultado para el archivo.",
      }
    );
  }

  async function uploadAll() {
    if (!session || !current || uploadFiles.length === 0) return;
    setUploading(true);
    setError("");
    const results: UploadItem[] = [];
    let created = 0;
    try {
      for (const file of uploadFiles) {
        try {
          const item = await uploadSingle(file, false);
          results.push(item);
          if (item.status === "created") created += 1;
        } catch (e) {
          results.push({
            filename: file.name,
            status: "error",
            error: uploadErrorMessage(e),
          });
        }
        setUploadItems([...results]);
      }
      const failed = new Set(
        results.filter((item) => item.status !== "created").map((item) => item.filename),
      );
      setUploadFiles((prev) => prev.filter((file) => failed.has(file.name)));
      if (created > 0) await runAnalyze();
    } finally {
      setUploading(false);
    }
  }

  async function retryUpload(item: UploadItem) {
    const file = uploadFiles.find((f) => f.name === item.filename);
    if (!file) return;
    setRetrying(item.filename);
    setError("");
    try {
      const result = await uploadSingle(file, true);
      setUploadItems((prev) =>
        prev.map((i) => (i.filename === item.filename ? result : i)),
      );
      if (result.status === "created") {
        setUploadFiles((prev) => prev.filter((f) => f !== file));
        await runAnalyze();
      }
    } catch (e) {
      setError(uploadErrorMessage(e));
    } finally {
      setRetrying("");
    }
  }

  async function runAnalyze() {
    if (!session || !current) return;
    setBusy(true);
    setError("");
    const token = session.token;
    const organizationId = session.organizationId;
    const id = current.id;
    const done = new Set(["REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION", "FAILED"]);
    let stopPoll = false;

    const pollOnce = async () => {
      const prog = await api<ProgressPayload>(`${API}/sessions/${id}/progress`, {
        token,
        organizationId,
      });
      setProgress(prog);
      setCurrent(prog.session);
      return prog;
    };

    void (async () => {
      for (let i = 0; i < 40; i++) {
        if (stopPoll) return;
        try {
          const prog = await pollOnce();
          if (done.has(prog.session.status)) return;
        } catch {
          /* progress optional during analyze */
        }
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }
    })();

    try {
      await api(`${API}/sessions/${id}/analyze`, {
        method: "POST",
        token,
        organizationId,
      });
      stopPoll = true;
      await pollOnce();
      const und = await api<Understanding>(`${API}/sessions/${id}/understanding`, {
        token,
        organizationId,
      });
      setUnderstanding(und);
      setUiStep("analyze");
    } catch (e) {
      stopPoll = true;
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      stopPoll = true;
      setBusy(false);
    }
  }

  async function goReview() {
    if (!session || !current) return;
    if (!canContinueAnalyze(current.status)) return;
    const und = await api<Understanding>(`${API}/sessions/${current.id}/understanding`, {
      token: session.token,
      organizationId: session.organizationId,
    });
    setUnderstanding(und);
    setUiStep("review");
  }

  async function review(id: string, action: "confirm" | "change" | "ignore", payload?: Record<string, unknown>) {
    if (!session || !current) return;
    setBusyId(id);
    try {
      await api(`${API}/sessions/${current.id}/review/${id}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ action, payload }),
      });
      const und = await api<Understanding>(`${API}/sessions/${current.id}/understanding`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setUnderstanding(und);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusyId("");
    }
  }

  async function freeText(text: string) {
    if (!session || !current) return;
    await api(`${API}/sessions/${current.id}/free-text`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({ text }),
    });
  }

  async function loadQuestions() {
    if (!session || !current) return;
    try {
      const data = await api<{ questions: Array<{ id: string; text: string }> }>(
        `${API}/sessions/${current.id}/questions`,
        { token: session.token, organizationId: session.organizationId }
      );
      setQuestions(data.questions || []);
      setUiStep("test");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function acceptReview() {
    if (!session || !current) return;
    setBusyId("accept-all");
    setError("");
    try {
      await api(`${API}/sessions/${current.id}/accept-review`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusyId("");
    }
  }

  async function ask(text: string) {
    if (!session || !current) return;
    setBusy(true);
    setAskError("");
    setActiveQuestion(text);
    try {
      const data = await api<Record<string, unknown>>(`${API}/sessions/${current.id}/ask`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ question: text }),
      });
      setAnswer(data);
    } catch (e) {
      setAnswer(null);
      setAskError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function feedback(verdict: string, reason?: string) {
    if (!session || !current) return;
    await api(`${API}/sessions/${current.id}/answer-feedback`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({ verdict, reason, question: answer?.question }),
    });
  }

  async function skip(what: "review" | "test") {
    if (!session || !current) return;
    const data = await api<OnboardingSession>(`${API}/sessions/${current.id}/skip/${what}`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
    });
    setCurrent(data);
    if (what === "review") await loadQuestions();
    else await finish();
  }

  async function finish() {
    if (!session || !current) return;
    await api(`${API}/sessions/${current.id}/complete`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
    });
    const data = await api<ReadinessPayload>(`${API}/sessions/${current.id}/readiness`, {
      token: session.token,
      organizationId: session.organizationId,
    });
    setReadiness(data);
    setUiStep("ready");
  }

  function selectStep(id: string) {
    const step = id as WizardStep;
    if (step === "test" && questions.length === 0) {
      void loadQuestions();
      return;
    }
    setUiStep(step);
  }

  async function startDrive() {
    if (!session || !current) return;
    const data = await api<OnboardingSession & { authorization_url?: string }>(
      `${API}/sessions/${current.id}/connect/drive/start`,
      {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: "Google Drive" }),
      }
    );
    setCurrent(data);
    setAuthorizationUrl(data.authorization_url || "");
    if (data.authorization_url) window.location.assign(data.authorization_url);
  }

  async function pickFolder(id: string) {
    if (!session || !current) return;
    const data = await api<OnboardingSession>(`${API}/sessions/${current.id}/connect/drive/folder`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({ folder_id: id }),
    });
    setCurrent(data);
    setUiStep("analyze");
  }

  const kind = current?.kind;
  const suggestions = (understanding.suggestions || []) as Suggestion[];
  const analyzeReady = canContinueAnalyze(current?.status);

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.add}
        subtitle="Conecta tus datos. Zent los entiende contigo."
      />
      <ErrorInline message={error} />
      {current?.warning && <WarningInline message={current.warning} />}
      {current && (
        <div className="rounded-lg border border-border bg-surface p-2 shadow-panel">
          <Stepper
            steps={WIZARD_STEPS}
            active={uiStep === "confirm" ? "review" : uiStep}
            onSelect={selectStep}
          />
        </div>
      )}
      <div className="mt-6">    
      {uiStep === "choose" && <SourceTypeStep onSelect={startKind} />}
      {current && uiStep === "connect" && kind === "database" && (
        <>
          <DatabaseConnectionStep onSubmit={connectDatabase} busy={busy} result={dbResult} />
          {dbResult?.ok && (
            <button type="button" className="btn btn-primary mt-4" onClick={runAnalyze}>
              Continuar
            </button>
          )}
        </>
      )}
      {current && uiStep === "connect" && (kind === "documents" || kind === "spreadsheets") && (
        <>
          <FileUploadStep
            onFiles={addUploadFiles}
            files={uploadFiles}
            items={uploadItems}
            onRemove={(file) =>
              setUploadFiles((prev) => prev.filter((f) => f !== file))
            }
            onRetry={(item) => void retryUpload(item)}
            onClear={() => {
              setUploadFiles([]);
              setUploadItems([]);
            }}
            onSubmit={() => void uploadAll()}
            busy={uploading}
            retrying={retrying}
          />
          {current.kb_source_id && !uploading && (
            <button type="button" className="btn btn-primary mt-4" onClick={runAnalyze}>
              Continuar
            </button>
          )}
        </>
      )}
      {current && uiStep === "connect" && kind === "drive" && (
        <DriveStep
          onStart={startDrive}
          onSelectFolder={pickFolder}
          onManualId={pickFolder}
          authorizationUrl={authUrl}
          folders={folders}
          busy={busy}
        />
      )}
      {current && uiStep === "connect" && kind === "website" && (
        <WebsiteStep
          busy={busy}
          preview={webPreview}
          onPreview={async (url) => {
            setWebUrl(url);
            if (!session || !current) return;
            const data = await api<OnboardingSession & { preview?: typeof webPreview }>(
              `${API}/sessions/${current.id}/connect/web`,
              {
                method: "POST",
                token: session.token,
                organizationId: session.organizationId,
                body: JSON.stringify({ url, commit: false }),
              }
            );
            setWebPreview(data.preview);
          }}
          onCommit={async () => {
            if (!session || !current) return;
            const data = await api<OnboardingSession>(`${API}/sessions/${current.id}/connect/web`, {
              method: "POST",
              token: session.token,
              organizationId: session.organizationId,
              body: JSON.stringify({ url: webUrl, commit: true }),
            });
            setCurrent(data);
            setUiStep("analyze");
          }}
        />
      )}
      {current && uiStep === "connect" && kind === "api" && (
        <>
          <ApiStep
            busy={busy}
            result={apiResult}
            onSubmit={async (body) => {
              if (!session || !current) return;
              setBusy(true);
              try {
                const data = await api<OnboardingSession>(`${API}/sessions/${current.id}/connect/api`, {
                  method: "POST",
                  token: session.token,
                  organizationId: session.organizationId,
                  body: JSON.stringify(body),
                });
                setCurrent(data);
                setApiResult(data.connection);
                if (data.connection?.ok) setUiStep("analyze");
              } catch (e) {
                setError(e instanceof Error ? e.message : "Error");
              } finally {
                setBusy(false);
              }
            }}
          />
          {apiResult?.ok && (
            <button type="button" className="btn btn-primary mt-4" onClick={runAnalyze}>
              Continuar
            </button>
          )}
        </>
      )}
      {uiStep === "analyze" && (
        <AnalysisProgressStep
          headline={progress?.headline || "Zent está entendiendo tus datos"}
          phases={progress?.phases || []}
          technical={progress?.technical_details}
          showTech={tech}
          onToggleTech={() => setTech((v) => !v)}
          onContinue={goReview}
          ready={analyzeReady}
          percent={progress?.percent}
          glimpses={progress?.glimpses}
          files={progress?.technical_details?.files ?? []}
          status={current?.status}
        />
      )}
      {uiStep === "review" && (
        <UnderstandingReviewStep
          understanding={understanding}
          suggestions={suggestions}
          onReview={review}
          onFreeText={freeText}
          onSkip={() => skip("review")}
          onAcceptAll={acceptReview}
          busy={busyId}
        />
      )}
      {uiStep === "test" && (
        <>
          <QuestionValidationStep
            questions={questions}
            answer={answer}
            onAsk={ask}
            onFeedback={feedback}
            onSkip={() => skip("test")}
            busy={busy}
            heading={current ? FLOW_QUESTION_HEADING[current.kind] ?? FLOW_QUESTION_HEADING.default : undefined}
            askError={askError || null}
            activeQuestion={activeQuestion}
          />
          <button type="button" className="btn btn-primary mt-4" data-testid="finish-wizard" onClick={finish}>
            Terminar
          </button>
        </>
      )}
      {uiStep === "ready" && readiness && (
        <ReadinessStep
          overall={readiness.overall}
          scores={readiness.scores}
          labels={readiness.labels}
          improvements={readiness.improvements}
          warning={current?.warning || null}
          readyHeadline={readiness.ready_headline}
          readySubtitle={readiness.ready_subtitle}
          readyActions={readiness.ready_actions}
          tabular={readiness.tabular}
        />
      )}
      </div>
    </KnowledgeLayout>
  );
}
