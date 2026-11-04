/**
 * Estado visible del Workflow Studio. Separa dos ejes que antes se mezclaban
 * en la cabecera (badge «Borrador» + switch «Activo» + «Cambios sin guardar»):
 *
 * - persistencia del borrador: sin guardar / guardando / guardado / error.
 * - ciclo de vida de publicación: borrador sin publicar / publicado activo /
 *   publicado pausado / archivado, con aviso si el borrador difiere de lo
 *   publicado.
 *
 * Un solo eje por indicador evita estados aparentemente contradictorios.
 */
import type { Tone } from "../components/ui/Badge";

export type PersistenceInput = {
  dirty: boolean;
  saving: boolean;
  saveError?: string | null;
  /** Flash breve tras un guardado correcto. */
  justSaved?: boolean;
};

export type LifecycleInput = {
  status: string;
  publishedVersion?: number | null;
  /** El servidor indica que el borrador guardado difiere de la versión publicada. */
  draftChanged?: boolean;
  dirty?: boolean;
};

export type Indicator = { key: string; label: string; tone: Tone; detail?: string };

export function persistenceIndicator(input: PersistenceInput): Indicator {
  if (input.saving) return { key: "saving", label: "Guardando…", tone: "info" };
  if (input.saveError) {
    return { key: "error", label: "Error al guardar", tone: "danger", detail: input.saveError };
  }
  if (input.dirty) {
    return {
      key: "dirty",
      label: "Cambios sin guardar",
      tone: "warn",
      detail: "Se guardan solos en unos segundos o con Ctrl+S.",
    };
  }
  if (input.justSaved) return { key: "saved", label: "Guardado", tone: "ok" };
  return { key: "clean", label: "Borrador guardado", tone: "neutral" };
}

export function lifecycleIndicator(input: LifecycleInput): Indicator {
  const version = input.publishedVersion ? ` v${input.publishedVersion}` : "";
  const pending = input.draftChanged || input.dirty;
  switch (input.status) {
    case "active":
      return {
        key: "active",
        label: `Publicado${version} · activo`,
        tone: "ok",
        detail: pending ? "El borrador tiene cambios que aún no están publicados." : undefined,
      };
    case "paused":
      return {
        key: "paused",
        label: `Publicado${version} · pausado`,
        tone: "warn",
        detail: pending ? "El borrador tiene cambios que aún no están publicados." : undefined,
      };
    case "archived":
      return { key: "archived", label: "Archivado", tone: "neutral" };
    case "draft":
      return {
        key: "draft",
        label: input.publishedVersion ? `Borrador · última publicación${version}` : "Borrador sin publicar",
        tone: "neutral",
      };
    default:
      return { key: input.status || "unknown", label: `Estado: ${input.status || "desconocido"}`, tone: "neutral" };
  }
}

/** Resumen de una línea de la ficha de misión para la cabecera. */
export function missionSummary(mission: Partial<Record<"role" | "audience" | "goal", string>>): string {
  const goal = (mission.goal ?? "").trim();
  if (goal) return goal;
  const role = (mission.role ?? "").trim();
  const audience = (mission.audience ?? "").trim();
  if (role && audience) return `${role} para ${audience}`;
  return role || audience;
}

/** ¿Hay cambios del borrador pendientes de publicar? (para el punto del botón Publicar). */
export function hasUnpublishedChanges(input: LifecycleInput): boolean {
  if (input.status !== "active" && input.status !== "paused") return false;
  return Boolean(input.draftChanged || input.dirty);
}
