import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import { useAuth } from "../../../auth";
import { ErrorInline, PageHeader } from "../../../components/ui";
import { KnowledgeLayout } from "../../../components/KnowledgeLayout";
import { Stepper } from "../../../components/Stepper";
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
  const [readiness, setReadiness] = useState<ReadinessPayload | null>(null);
  const [folders, setFolders] = useState<Array<{ id: string; name: string }>>([]);
  const [authUrl, setAuthorizationUrl] = useState("");
  const [webPreview, setWebPreview] = useState<{ url?: string; host?: string; pages_detected?: number }>();
  const [webUrl, setWebUrl] = useState("");
  const [dbResult, setDbResult] = useState<OnboardingSession["connection"]>();
  const [apiResult, setApiResult] = useState<OnboardingSession["connection"]>();
  const [uiStep, setUiStep] = useState<WizardStep>("choose");

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

  async function uploadFile(file: File) {
    if (!session || !current) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await api<OnboardingSession>(`${API}/sessions/${current.id}/connect/upload`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: form,
      });
      setCurrent(data);
      setUiStep("analyze");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function runAnalyze() {
    if (!session || !current) return;
    setBusy(true);
    setError("");
    try {
      await api(`${API}/sessions/${current.id}/analyze`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      const done = new Set(["REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION", "FAILED"]);
      for (let i = 0; i < 40; i++) {
        const prog = await api<ProgressPayload>(`${API}/sessions/${current.id}/progress`, {
          token: session.token,
          organizationId: session.organizationId,
        });
        setProgress(prog);
        setCurrent(prog.session);
        if (done.has(prog.session.status)) break;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      const und = await api<Understanding>(`${API}/sessions/${current.id}/understanding`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setUnderstanding(und);
      setUiStep("analyze");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function goReview() {
    if (!session || !current) return;
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
    const data = await api<{ questions: Array<{ id: string; text: string }> }>(
      `${API}/sessions/${current.id}/questions`,
      { token: session.token, organizationId: session.organizationId }
    );
    setQuestions(data.questions || []);
    setUiStep("test");
  }

  async function ask(text: string) {
    if (!session || !current) return;
    setBusy(true);
    try {
      const data = await api<Record<string, unknown>>(`${API}/sessions/${current.id}/ask`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ question: text }),
      });
      setAnswer(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
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
  const analyzeReady = Boolean(
    current &&
      ["REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION"].includes(current.status)
  );

  return (
    <KnowledgeLayout>
      <PageHeader
        title="Añade conocimiento a Zent"
        subtitle="Conecta tus datos. Zent los entiende contigo."
      />
      <ErrorInline message={error} />
      {current?.warning && (
        <div className="mb-4 rounded-md border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
          {current.warning}
        </div>
      )}
      {current && (
        <Stepper
          steps={WIZARD_STEPS}
          active={uiStep === "confirm" ? "review" : uiStep}
          onSelect={(id) => setUiStep(id as WizardStep)}
        />
      )}
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
            onFile={uploadFile}
            busy={busy}
            filename={typeof current.state.filename === "string" ? current.state.filename : undefined}
          />
          {current.kb_source_id && (
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
        />
      )}
      {uiStep === "review" && (
        <>
          <UnderstandingReviewStep
            understanding={understanding}
            suggestions={suggestions}
            onReview={review}
            onFreeText={freeText}
            onSkip={() => skip("review")}
            busy={busyId}
          />
          <button type="button" className="btn btn-primary mt-4" data-testid="goto-questions" onClick={loadQuestions}>
            Continuar a preguntas
          </button>
        </>
      )}
      {uiStep === "test" && (
        <QuestionValidationStep
          questions={questions}
          answer={answer as { question?: string; answer?: string; method?: string; sql?: string | null; confidence?: string; evidence?: string[] } | null}
          onAsk={ask}
          onFeedback={feedback}
          onSkip={() => skip("test")}
          busy={busy}
          heading={current ? FLOW_QUESTION_HEADING[current.kind] ?? FLOW_QUESTION_HEADING.default : undefined}
        />
      )}
      {uiStep === "test" && (
        <button type="button" className="btn btn-primary mt-4" data-testid="finish-wizard" onClick={finish}>
          Terminar
        </button>
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
        />
      )}
    </KnowledgeLayout>
  );
}
