/**
 * Coreografía de la entrada: la cámara se mete en la red, la luz llena el
 * cuadro y la cortina de relevo sostiene esa misma luz mientras cambia la ruta.
 *
 * Vive fuera de React y del DOM a propósito: el canvas, la cortina y las
 * páginas de acceso leen los mismos números, así el zoom, el bloom y la
 * disolución empatan sin acoplarse entre sí.
 */

/** Duración del zoom de entrada: anticipación, travesía y bloom. */
export const DIVE_MS = 1180;
/** Con `prefers-reduced-motion` no hay zoom: sólo una espera corta. */
export const DIVE_REDUCED_MS = 300;
/** Ventana final del bloom dentro del zoom. */
export const BLOOM_MS = 320;
/** Disolución de la cortina sobre el panel, ya montado. */
export const ENTRY_REVEAL_MS = 680;
/** Ampliación final de la cámara. */
export const DIVE_ZOOM = 5.4;
/** Canales de la luz final. El mismo color va en `.auth-dive-bloom` y `.auth-entry-curtain`. */
export const DIVE_BLOOM = "236, 255, 249";
/** Si nadie llega a destino, el tránsito caduca: la cortina nunca queda colgada. */
export const ENTRY_EXPIRY_MS = 5200;

export type EntryTransit = {
  armed: boolean;
  /** Marca de tiempo del armado (ms). */
  at: number;
  reduced: boolean;
};

const idle: EntryTransit = { armed: false, at: 0, reduced: false };

let state: EntryTransit = idle;
const listeners = new Set<(state: EntryTransit) => void>();

function publish(): void {
  for (const listener of listeners) listener(state);
}

/** Arranca el tránsito: la cortina se prepara y el panel sabrá que viene de un acceso. */
export function armEntry({ reduced = false }: { reduced?: boolean } = {}): void {
  state = { armed: true, at: Date.now(), reduced };
  publish();
}

/** Cancela el tránsito: un error de credenciales no deja cortina preparada. */
export function disarmEntry(): void {
  if (!state.armed) return;
  state = idle;
  publish();
}

/** ¿Sigue en curso el tránsito? Caduca solo si nunca se llegó al panel. */
export function entryArmed(): boolean {
  return state.armed && Date.now() - state.at < ENTRY_EXPIRY_MS;
}

export function subscribeEntry(listener: (state: EntryTransit) => void): () => void {
  listener(state);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
