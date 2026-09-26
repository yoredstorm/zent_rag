import type { NetStats } from "../../lib/neuralNet";

/**
 * Bus mínimo entre la UI del acceso y la red neuronal.
 *
 * El canvas escucha foco / envío / error / éxito y reacciona; el shell escucha
 * lo mismo para iluminar el dock y el estado de la tarjeta. Va por fuera de
 * React a propósito: los eventos ocurren en el pointer del formulario y no
 * tienen por qué provocar renders.
 */
export type NeuralEvent =
  | { type: "focus"; zone: "email" | "password" | null }
  | { type: "submit" }
  | { type: "error" }
  | { type: "success" }
  | { type: "stats"; stats: NetStats };

type Listener = (event: NeuralEvent) => void;

const listeners = new Set<Listener>();

export function emitNeuralEvent(event: NeuralEvent): void {
  for (const listener of listeners) listener(event);
}

export function onNeuralEvent(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
