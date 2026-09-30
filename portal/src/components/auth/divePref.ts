/**
 * Preferencia del zoom de entrada. El dive es pesado (cámara en canvas).
 * Quien no tenga GPU lo apaga; el resto entra con la travesía completa.
 * `prefers-reduced-motion` siempre manda: ahí no hay zoom aunque esté "on".
 */

export const DIVE_PREF_KEY = "zent-auth-dive";

const listeners = new Set<(on: boolean) => void>();

function read(): boolean {
  try {
    return localStorage.getItem(DIVE_PREF_KEY) !== "off";
  } catch {
    return true;
  }
}

/** ¿El usuario quiere el zoom de entrada? */
export function diveEffectOn(): boolean {
  return read();
}

export function setDiveEffect(on: boolean): void {
  try {
    localStorage.setItem(DIVE_PREF_KEY, on ? "on" : "off");
  } catch {
    /* private mode */
  }
  for (const listener of listeners) listener(on);
}

export function subscribeDiveEffect(listener: (on: boolean) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Sin zoom: movimiento reducido del sistema o el usuario apagó el efecto. */
export function diveQuiet(reduceMotion: boolean | null | undefined): boolean {
  return Boolean(reduceMotion) || !diveEffectOn();
}
