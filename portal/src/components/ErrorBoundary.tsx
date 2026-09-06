import { Component, type ErrorInfo, type ReactNode } from "react";
import { isApiError } from "../lib/errors";
import { reportComponentError } from "../lib/observability";

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary:", error, info.componentStack);
    reportComponentError(error);
  }

  render() {
    if (this.state.error) {
      const err = this.state.error;
      const traceId = isApiError(err) ? err.traceId : null;
      return (
        <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center">
          <h1 className="text-lg font-semibold text-text">Algo salió mal</h1>
          <p className="max-w-md text-sm leading-relaxed text-muted">
            Ocurrió un error inesperado. Recarga la página para continuar.
          </p>
          {err.message && (
            <p className="max-w-md truncate rounded-md border border-border bg-soft px-3 py-2 font-mono text-xs text-muted">
              {err.message}
            </p>
          )}
          {traceId && (
            <p className="font-mono text-[11px] text-faint">trace: {traceId}</p>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => window.location.reload()}
          >
            Recargar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}