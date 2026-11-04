/**
 * Favoritos y recientes del catálogo de nodos (por navegador). Solo guardan
 * tipos de nodo: la disponibilidad real sigue viniendo del catálogo backend.
 */
const FAVORITES_KEY = "zent.wf.catalog.favorites.v1";
const RECENTS_KEY = "zent.wf.catalog.recents.v1";
export const MAX_RECENTS = 6;

function readList(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function writeList(key: string, list: string[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(list));
  } catch {
    // sin persistencia
  }
}

export function loadFavorites(): string[] {
  return readList(FAVORITES_KEY);
}

export function toggleFavorite(type: string): string[] {
  const current = loadFavorites();
  const next = current.includes(type) ? current.filter((t) => t !== type) : [...current, type];
  writeList(FAVORITES_KEY, next);
  return next;
}

export function loadRecents(): string[] {
  return readList(RECENTS_KEY);
}

export function pushRecent(type: string): string[] {
  const next = [type, ...loadRecents().filter((t) => t !== type)].slice(0, MAX_RECENTS);
  writeList(RECENTS_KEY, next);
  return next;
}
