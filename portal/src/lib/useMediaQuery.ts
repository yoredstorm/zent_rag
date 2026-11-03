import { useCallback, useSyncExternalStore } from "react";

/**
 * Media query reactiva sin listeners manuales en cada componente.
 * En SSR/test sin `matchMedia` devuelve `fallback`.
 */
export function useMediaQuery(query: string, fallback = false): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
        return () => undefined;
      }
      const media = window.matchMedia(query);
      media.addEventListener("change", onStoreChange);
      return () => media.removeEventListener("change", onStoreChange);
    },
    [query],
  );

  const getSnapshot = useCallback(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return fallback;
    return window.matchMedia(query).matches;
  }, [query, fallback]);

  return useSyncExternalStore(subscribe, getSnapshot, () => fallback);
}
