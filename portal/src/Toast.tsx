import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ToastKind = "info" | "success" | "error" | "warn";

export type ToastItem = {
  id: string;
  kind: ToastKind;
  title: string;
  body?: string;
};

type ToastContextValue = {
  toasts: ToastItem[];
  pushToast: (kind: ToastKind, title: string, body?: string) => void;
  dismissToast: (id: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

let toastSeq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (kind: ToastKind, title: string, body?: string) => {
      const id = `toast-${++toastSeq}-${Date.now()}`;
      setToasts((prev) => [...prev.slice(-4), { id, kind, title, body }]);
      const ttl = kind === "error" || kind === "warn" ? 8000 : 4500;
      window.setTimeout(() => dismissToast(id), ttl);
    },
    [dismissToast]
  );

  const value = useMemo(
    () => ({ toasts, pushToast, dismissToast }),
    [toasts, pushToast, dismissToast]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`} role="status">
            <div className="toast-title">{t.title}</div>
            {t.body && <div className="toast-body">{t.body}</div>}
            <button
              type="button"
              className="toast-close"
              aria-label="Cerrar"
              onClick={() => dismissToast(t.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast outside ToastProvider");
  return ctx;
}
