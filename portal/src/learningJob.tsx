// =============================================================================
// LearningJob — seguimiento global de una sesión de aprendizaje
// =============================================================================
// Sobrevive la navegación: el banner vive en el layout de la app, el estado se
// reanuda desde sessionStorage o descubre la última sesión activa del tenant.
// Al terminar avisa con toast y sube `version` para que las páginas (Fuentes,
// Detalle, Home) refresquen solas, sin F5.
// =============================================================================
import { CircleNotch, GraduationCap, X } from "@phosphor-icons/react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import {
  fetchLearningSession,
  fetchLearningSessions,
  type LearningSessionDetail,
} from "./lib/knowledgeSessions";
import { useToast } from "./Toast";

const POLL_MS = 4000;
const RESUME_MAX_MS = 30 * 60 * 1000;
const AUTO_CLEAR_MS = 15_000;
const TERMINAL = ["completed", "partial", "failed", "canceled"];

// Avance mínimo por etapa: el rail nunca se ve vacío mientras ZENT lee.
const STAGE_PERCENT: Record<string, number> = {
  reading: 12,
  understanding: 32,
  organizing: 52,
  connecting: 68,
  verifying: 84,
  learned: 100,
};

type LearningJobContextValue = {
  sessionId: string | null;
  detail: LearningSessionDetail | null;
  active: boolean;
  /** Sube cuando el aprendizaje terminó: las páginas se refrescan con esto. */
  version: number;
  track: (sessionId: string, initial?: LearningSessionDetail | null) => void;
  clear: () => void;
};

const LearningJobContext = createContext<LearningJobContextValue | null>(null);

// Fuera del provider (tests o páginas aisladas) el seguimiento es un no-op:
// las páginas siguen funcionando sin banner global.
const FALLBACK: LearningJobContextValue = {
  sessionId: null,
  detail: null,
  active: false,
  version: 0,
  track: () => {},
  clear: () => {},
};

function storageKey(organizationId: string) {
  return `rag_learning_session_${organizationId}`;
}

export function LearningJobProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LearningSessionDetail | null>(null);
  const [version, setVersion] = useState(0);
  const terminalToasted = useRef<string | null>(null);
  const autoClearTimer = useRef<number | null>(null);

  const clear = useCallback(() => {
    if (session) sessionStorage.removeItem(storageKey(session.organizationId));
    if (autoClearTimer.current) {
      window.clearTimeout(autoClearTimer.current);
      autoClearTimer.current = null;
    }
    setSessionId(null);
    setDetail(null);
  }, [session]);

  const track = useCallback(
    (id: string, initial?: LearningSessionDetail | null) => {
      if (session) {
        sessionStorage.setItem(
          storageKey(session.organizationId),
          JSON.stringify({ id, at: Date.now() }),
        );
      }
      terminalToasted.current = null;
      setSessionId(id);
      setDetail(initial ?? null);
    },
    [session],
  );

  // Reanudar: sesión guardada de esta pestaña u otra sesión activa del tenant.
  useEffect(() => {
    if (!session) {
      setSessionId(null);
      setDetail(null);
      return;
    }
    const raw = sessionStorage.getItem(storageKey(session.organizationId));
    if (raw) {
      try {
        const saved = JSON.parse(raw) as { id?: string; at?: number };
        if (
          saved.id &&
          typeof saved.at === "number" &&
          Date.now() - saved.at < RESUME_MAX_MS
        ) {
          setSessionId(saved.id);
          setDetail(null);
          return;
        }
      } catch {
        // registro corrupto: se descarta
      }
      sessionStorage.removeItem(storageKey(session.organizationId));
    }

    let cancelled = false;
    fetchLearningSessions(6)
      .then(({ sessions }) => {
        if (cancelled) return;
        const activeSession = sessions.find((item) => !TERMINAL.includes(item.status));
        if (activeSession) track(activeSession.session_id, activeSession);
      })
      .catch(() => {
        // descubrir la sesión es best-effort
      });
    return () => {
      cancelled = true;
    };
  }, [session, track]);

  // Poll de respaldo mientras la sesión siga viva.
  useEffect(() => {
    if (!session || !sessionId) return;
    if (detail && TERMINAL.includes(detail.status)) return;

    let stopped = false;
    const poll = async () => {
      try {
        const fresh = await fetchLearningSession(sessionId);
        if (stopped) return;
        setDetail(fresh);
        if (TERMINAL.includes(fresh.status)) {
          if (terminalToasted.current !== sessionId) {
            terminalToasted.current = sessionId;
            setVersion((value) => value + 1);
            // `available_sources` cuenta fuentes consultables (estado intermedio):
            // al completar puede quedar en 0. El total sí es la verdad.
            const summary = `${fresh.source_count} fuente${
              fresh.source_count === 1 ? "" : "s"
            } aprendida${fresh.source_count === 1 ? "" : "s"}`;
            if (fresh.status === "completed") {
              pushToast("success", "ZENT terminó de aprender", summary);
            } else if (fresh.status === "partial") {
              pushToast("warn", "Aprendizaje parcial", summary);
            } else {
              pushToast("error", "El aprendizaje falló", fresh.title || summary);
            }
            if (autoClearTimer.current) window.clearTimeout(autoClearTimer.current);
            autoClearTimer.current = window.setTimeout(() => clear(), AUTO_CLEAR_MS);
          }
        }
      } catch {
        // el poll de respaldo no tumba la navegación
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [session, sessionId, detail?.status, pushToast, clear]); // eslint-disable-line react-hooks/exhaustive-deps

  const active = Boolean(
    sessionId && (!detail || !TERMINAL.includes(detail.status)),
  );

  const value = useMemo(
    () => ({ sessionId, detail, active, version, track, clear }),
    [sessionId, detail, active, version, track, clear],
  );

  return (
    <LearningJobContext.Provider value={value}>{children}</LearningJobContext.Provider>
  );
}

export function useLearningJob() {
  return useContext(LearningJobContext) ?? FALLBACK;
}

export function LearningBanner() {
  const { sessionId, detail, active, clear } = useLearningJob();
  const location = useLocation();
  if (!sessionId || !detail) return null;
  // En la página de su propia sesión el banner sería redundante.
  if (location.pathname === `/knowledge/sessions/${sessionId}`) return null;

  const terminal = !active;
  const failed = detail.status === "failed" || detail.status === "canceled";
  const ratio =
    detail.source_count > 0 ? (detail.available_sources / detail.source_count) * 100 : 0;
  const stagePercent = STAGE_PERCENT[detail.stage] ?? 6;
  const percent = failed
    ? Math.min(stagePercent, 100)
    : terminal
      ? 100
      : Math.max(stagePercent, ratio);

  const state = failed
    ? "failed"
    : detail.status === "partial"
      ? "partial"
      : terminal
        ? "completed"
        : "running";

  const title = failed
    ? "El aprendizaje no terminó"
    : terminal
      ? detail.status === "partial"
        ? "Aprendizaje parcial"
        : "Aprendizaje completado"
      : "ZENT está aprendiendo";

  const delta = detail.knowledge_delta ?? {};
  const deltaText = [
    delta.new_concepts ? `${delta.new_concepts} conceptos` : "",
    delta.new_facts ? `${delta.new_facts} hechos` : "",
    delta.new_relationships ? `${delta.new_relationships} relaciones` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const sourcesLabel = `${detail.source_count} fuente${
    detail.source_count === 1 ? "" : "s"
  }`;

  return (
    <div
      className={`state-rail lj-banner mb-5 flex flex-col gap-2 rounded-md border px-4 py-3 shadow-pop ${
        failed
          ? "border-danger/30 bg-danger-soft"
          : terminal
            ? "border-ok/30 bg-ok-soft"
            : "border-accent/25 bg-accent-soft/40"
      }`}
      data-state={state}
      role="status"
      data-testid="learning-banner"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border bg-surface ${
            failed ? "border-danger/30 text-danger" : "border-accent/25 text-accent"
          }`}
        >
          {terminal ? (
            <GraduationCap size={16} aria-hidden />
          ) : (
            <CircleNotch size={16} className="animate-spin" aria-hidden />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-text">
            {title}
            {!terminal && detail.title ? (
              <span className="font-normal text-muted"> · {detail.title}</span>
            ) : null}
          </span>
          <span className="block text-[12.5px] leading-relaxed text-muted">
            {terminal
              ? deltaText || `${sourcesLabel} aprendida${detail.source_count === 1 ? "" : "s"}`
              : `${detail.stage_label || "Leyendo"} · ${sourcesLabel}`}
          </span>
        </span>
        <Link
          to={`/knowledge/sessions/${sessionId}`}
          className="btn btn-secondary btn-sm shrink-0"
        >
          {terminal ? "Ver resumen" : "Ver sesión"}
        </Link>
        <button
          type="button"
          className="btn btn-ghost btn-icon h-8 w-8 min-h-0 shrink-0"
          aria-label="Cerrar aviso de aprendizaje"
          onClick={clear}
        >
          <X size={14} aria-hidden />
        </button>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${failed ? "bg-danger" : ""}`}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
    </div>
  );
}
