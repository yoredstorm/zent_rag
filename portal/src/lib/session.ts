import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Idle timeout (FASE 06): vigila actividad del usuario y avisa antes de
 * cerrar la sesión. Devuelve los segundos restantes (<=0 = timeout).
 */
export function useIdleTimeout({
  minutes,
  onTimeout,
}: {
  minutes: number;
  onTimeout: () => void;
}): number {
  const [remaining, setRemaining] = useState<number>(() => minutes * 60);
  const lastActivity = useRef(0);
  const onTimeoutRef = useRef(onTimeout);

  useEffect(() => {
    onTimeoutRef.current = onTimeout;
  }, [onTimeout]);

  useEffect(() => {
    if (!minutes || minutes <= 0) return;
    lastActivity.current = Date.now();
    setRemaining(minutes * 60);
    const events: (keyof WindowEventMap)[] = ["mousemove", "keydown", "click", "scroll", "touchstart"];
    const onActivity = () => {
      lastActivity.current = Date.now();
    };
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    const tick = window.setInterval(() => {
      const idle = Math.floor((Date.now() - lastActivity.current) / 1000);
      const left = minutes * 60 - idle;
      setRemaining(left);
      if (left <= 0) onTimeoutRef.current();
    }, 5000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      window.clearInterval(tick);
    };
  }, [minutes]);

  return remaining;
}

/** Modal de advertencia de sesión inactiva. */
export function useIdleWarning(minutes: number, onLogout: () => void) {
  const remaining = useIdleTimeout({ minutes, onTimeout: useCallback(() => onLogout(), [onLogout]) });
  const show = remaining <= 60 && remaining > 0;
  return { remaining, show };
}