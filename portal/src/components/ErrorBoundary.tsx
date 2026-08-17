import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center">
          <h1 className="text-lg font-semibold text-text">Algo salió mal</h1>
          <p className="max-w-md text-sm leading-relaxed text-muted">
            Ocurrió un error inesperado. Recarga la página para continuar.
          </p>
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
