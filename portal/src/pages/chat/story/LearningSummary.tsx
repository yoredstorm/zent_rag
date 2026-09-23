// =============================================================================
// LearningSummary — qué experiencia previa usó y qué observación generó
// (§27, §28, §51)
// =============================================================================
// Respeta el ciclo de vida de Memory: "utilizó experiencia previa" no es lo
// mismo que "generó una nueva observación", y no se dice "Zent aprendió" si
// sólo hubo una observación.
import { Badge } from "../../../components/ui";
import { MemoryImpact, type ImpactLoad, type QueryImpact } from "../MemoryImpact";

export function LearningSummary({
  state,
  impact,
  memoryHits = 0,
}: {
  state: ImpactLoad;
  impact: QueryImpact | null;
  /** Memorias que entraron por Company Context en el razonamiento. */
  memoryHits?: number;
}) {
  const counts = impact?.counts;
  const used = counts?.used ?? memoryHits;
  const created = counts?.created ?? 0;
  const reinforced = counts?.reinforced ?? 0;
  const contradicted = counts?.contradicted ?? 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2 text-[11.5px]">
        <Badge tone={used ? "accent" : "neutral"}>
          Experiencia previa utilizada: {used}
        </Badge>
        <Badge tone={created ? "info" : "neutral"}>Nuevas observaciones: {created}</Badge>
        {reinforced ? <Badge tone="ok">Patrones reforzados: {reinforced}</Badge> : null}
        {contradicted ? <Badge tone="warn">Contradichos: {contradicted}</Badge> : null}
      </div>
      <p className="text-[11.5px] text-faint">
        {created
          ? "Se registró una observación operativa a partir de esta respuesta."
          : "Esta respuesta no generó observaciones nuevas."}
      </p>
      <MemoryImpact state={state} impact={impact} />
    </div>
  );
}

export default LearningSummary;
