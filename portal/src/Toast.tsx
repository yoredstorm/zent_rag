import {
  CheckCircle,
  Info,
  Warning,
  X,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
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

const KIND_META: Record<
  ToastKind,
  { icon: Icon; iconClass: string; barClass: string }
> = {
  info: { icon: Info, iconClass: "text-accent", barClass: "bg-accent" },
  success: { icon: CheckCircle, iconClass: "text-ok", barClass: "bg-ok" },
  error: { icon: XCircle, iconClass: "text-danger", barClass: "bg-danger" },
  warn: { icon: Warning, iconClass: "text-warn", barClass: "bg-warn" },
};

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
      <div
        className="fixed right-4 bottom-4 z-50 flex w-full max-w-[380px] flex-col gap-2"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const meta = KIND_META[t.kind];
          const IconEl = meta.icon;
          return (
            <div key={t.id} className="toast relative overflow-hidden" role="status">
              <span
                className={`absolute inset-y-0 left-0 w-[3px] ${meta.barClass}`}
                aria-hidden
              />
              <IconEl size={20} weight="fill" className={meta.iconClass} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-text">{t.title}</p>
                {t.body && (
                  <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{t.body}</p>
                )}
              </div>
              <button
                type="button"
                className="shrink-0 cursor-pointer rounded-xs p-1 text-faint transition-colors hover:bg-soft hover:text-text"
                aria-label="Cerrar"
                onClick={() => dismissToast(t.id)}
              >
                <X size={14} aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast outside ToastProvider");
  return ctx;
}
