// =============================================================================
// KnowledgeLearningOrb — señales reales analizadas en paralelo (FASE 33E)
// =============================================================================
// Círculo central "Z" + partículas orbitando que representan Schema, Relaciones,
// Significado, Vectores y Preguntas. La partícula activa corresponde a la etapa
// REAL del run (current_stage). Respeta prefers-reduced-motion vía el CSS global.
// =============================================================================
import { Database, Graph, Lightning, Question, Tag } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";

type Particle = {
  key: string;
  label: string;
  icon: Icon;
  stages: string[];
  duration: number;
};

const PARTICLES: Particle[] = [
  {
    key: "schema",
    label: "Schema",
    icon: Database,
    stages: ["connecting", "discovering_schema", "profiling"],
    duration: 16,
  },
  {
    key: "meaning",
    label: "Significado",
    icon: Tag,
    stages: ["detecting_entities", "analyzing_fields", "llm_reasoning"],
    duration: 22,
  },
  {
    key: "relations",
    label: "Relaciones",
    icon: Graph,
    stages: ["detecting_relationships"],
    duration: 19,
  },
  {
    key: "questions",
    label: "Preguntas",
    icon: Question,
    stages: ["generating_questions", "awaiting_validation"],
    duration: 26,
  },
  {
    key: "vectors",
    label: "Vectores",
    icon: Lightning,
    stages: ["chunking", "embedding", "indexing", "evaluating"],
    duration: 30,
  },
];

export function KnowledgeLearningOrb({
  activeStage,
  running = false,
  size = 168,
}: {
  activeStage?: string | null;
  running?: boolean;
  size?: number;
}) {
  return (
    <div
      className="kl-orb shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={
        running
          ? `Zent está analizando señales (${activeStage ?? "aprendiendo"})`
          : "Zent en reposo"
      }
      data-testid="learning-orb"
    >
      <div
        className="absolute inset-0 rounded-full border border-border"
        aria-hidden
      />
      <div
        className="absolute rounded-full border border-border/60"
        style={{ inset: size * 0.16 }}
        aria-hidden
      />
      {PARTICLES.map((particle, index) => {
        const active = Boolean(
          activeStage && particle.stages.includes(activeStage)
        );
        const ParticleIcon = particle.icon;
        return (
          <div
            key={particle.key}
            className="absolute inset-0"
            style={{ transform: `rotate(${index * (360 / PARTICLES.length)}deg)` }}
            aria-hidden
          >
            <div
              className={`kl-orbit ${index % 2 === 1 ? "kl-orbit-reverse" : ""}`}
              style={{ ["--kl-duration" as string]: `${particle.duration}s` }}
            >
              <span
                className="kl-particle flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-muted"
                data-active={active}
                title={particle.label}
                style={
                  active
                    ? { color: "var(--color-accent)", borderColor: "var(--color-accent)" }
                    : undefined
                }
              >
                <ParticleIcon size={13} weight={active ? "fill" : "regular"} />
              </span>
            </div>
          </div>
        );
      })}
      <div
        className={`absolute flex items-center justify-center rounded-full border border-accent/30 bg-accent-soft ${
          running ? "kl-core" : ""
        }`}
        style={{ inset: size * 0.28 }}
      >
        <span className="text-2xl font-semibold text-accent">Z</span>
      </div>
    </div>
  );
}
