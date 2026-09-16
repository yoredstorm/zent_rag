import { FlowArrow, MagicWand, PencilSimple, SquaresFour } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "../components/ui";
import type { WorkflowTemplate } from "../components/workflowStudio/types";

/** Mismo vocabulario humano que la lista de workflows. */
const TRIGGER_LABEL: Record<string, string> = {
  webhook: "cuando llega una llamada al hook",
  schedule: "según calendario",
  event: "cuando ocurre un evento",
};

function triggerLabel(trigger: string): string {
  return TRIGGER_LABEL[trigger] ?? trigger;
}

export default function WorkflowNewPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api<{ templates: WorkflowTemplate[] }>("/api/v1/workflows/templates", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setTemplates(data.templates || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  async function install(slug: string) {
    if (!session) return;
    setBusy(slug);
    setError("");
    try {
      const out = await api<{ workflow_id: string; hook_secret?: string }>(
        `/api/v1/workflows/templates/${slug}/install`,
        { method: "POST", token: session.token, organizationId: session.organizationId },
      );
      navigate(`/workflows/${out.workflow_id}`, { state: { hookSecret: out.hook_secret } });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      setBusy("");
    }
  }

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Workflows", to: "/workflows" }, { label: "Nuevo workflow" }]}
        title="¿Cómo quieres crear tu automatización?"
        subtitle="Contar qué necesitas es el camino recomendado; el lienzo avanzado y las plantillas siguen disponibles."
      />
      <ErrorInline message={error} />

      {/* Camino principal: describir en lenguaje de negocio */}
      <Panel className="border-accent/35 p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="eyebrow mb-2">Camino recomendado</p>
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-accent-line bg-accent-soft text-accent">
                <MagicWand size={18} weight="regular" aria-hidden />
              </span>
              <h2 className="text-h2">Crear con IA</h2>
            </div>
            <p className="prose-measure mt-3 text-[13px] leading-relaxed text-muted">
              Describe qué quieres automatizar con tus palabras. Zent lo traduce a un flujo y te lo
              muestra primero en lenguaje de negocio.
            </p>
            <ol className="mt-4 flex flex-col gap-2.5">
              <li className="flex items-start gap-2.5 text-[13px] text-muted">
                <span className="mono mt-px text-[11px] text-ghost">1</span>
                <span>
                  <span className="font-medium text-text">Escribes la necesidad</span> — por ejemplo
                  &ldquo;cuando una venta supere S/ 20,000, avisar al gerente comercial&rdquo;.
                </span>
              </li>
              <li className="flex items-start gap-2.5 text-[13px] text-muted">
                <span className="mono mt-px text-[11px] text-ghost">2</span>
                <span>
                  <span className="font-medium text-text">Zent te muestra lo que entendió</span>:
                  cuándo corre, qué condiciones evalúa y qué acciones ejecuta.
                </span>
              </li>
              <li className="flex items-start gap-2.5 text-[13px] text-muted">
                <span className="mono mt-px text-[11px] text-ghost">3</span>
                <span>
                  <span className="font-medium text-text">Tú confirmas</span> y recién ahí se crea.
                  Nada se ejecuta antes de tu aprobación.
                </span>
              </li>
            </ol>
          </div>
          <div className="flex shrink-0 flex-col gap-2 lg:w-[220px]">
            <ButtonLink
              to="/workflows/new/ask"
              variant="primary"
              leadingIcon={MagicWand}
              data-testid="wf-mode-ai"
            >
              Empezar a describir
            </ButtonLink>
            <p className="text-xs leading-relaxed text-faint">
              Sin nodos ni configuración técnica. Puedes volver al lienzo después.
            </p>
          </div>
        </div>
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {/* Alternativa manual */}
        <Panel className="flex flex-col">
          <PanelHeader
            title="Diseñar manualmente"
            description="Lienzo avanzado: nodos, puertos, condiciones, reintentos y control total del grafo."
          />
          <div className="flex min-w-0 flex-1 flex-col gap-3 p-4">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-raised text-muted">
                <PencilSimple size={18} weight="regular" aria-hidden />
              </span>
              <p className="text-[13px] text-muted">
                Para flujos que ya sabes cómo armar y quieres ajustar a mano cada paso.
              </p>
            </div>
            <p className="rounded-md bg-raised px-3 py-2 text-[12px] leading-relaxed text-faint">
              Elige este camino si necesitas condiciones compuestas, reintentos o llamar a la API de
              un sistema propio.
            </p>
            <ol className="flex flex-col gap-1.5 border-t border-border-soft pt-3">
              <li className="text-[12px] text-faint">
                1. Nombra el workflow — se abre el lienzo con el nodo de disparo listo.
              </li>
              <li className="text-[12px] text-faint">
                2. Arrastra nodos desde la biblioteca y conéctalos.
              </li>
              <li className="text-[12px] text-faint">
                3. Prueba con un payload real antes de activarlo.
              </li>
            </ol>
            <div className="mt-auto pt-1">
              <ButtonLink
                to="/workflows/new/manual"
                variant="secondary"
                leadingIcon={PencilSimple}
                data-testid="wf-mode-manual"
              >
                Abrir el lienzo
              </ButtonLink>
            </div>
          </div>
        </Panel>

        {/* Plantillas */}
        <Panel className="flex flex-col" data-testid="wf-mode-templates">
          <PanelHeader
            title="Usar una plantilla"
            description="Recetas listas para configurar y adaptar."
            actions={
              <ButtonLink to="/workflows/new/ask" variant="ghost" size="sm" leadingIcon={MagicWand}>
                Prefiero describirlo
              </ButtonLink>
            }
          />
          {loading ? (
            <div className="flex flex-col gap-2 p-4" aria-hidden>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 rounded-md" />
              ))}
            </div>
          ) : templates.length === 0 ? (
            <EmptyState
              compact
              icon={SquaresFour}
              title="Sin plantillas disponibles"
              body="Todavía no hay recetas publicadas para este workspace. Descríbelo con IA o arma el flujo en el lienzo."
            />
          ) : (
            <ul className="divide-y divide-border-soft">
              {templates.slice(0, 6).map((template) => (
                <li key={template.slug} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-soft text-faint">
                    <FlowArrow size={15} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-text">
                      {template.name}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-faint">
                      {template.steps.length} pasos · {triggerLabel(template.trigger_type)}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === template.slug}
                    data-testid={`wf-new-install-${template.slug}`}
                    onClick={() => void install(template.slug)}
                  >
                    {busy === template.slug ? "Instalando…" : "Usar"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
