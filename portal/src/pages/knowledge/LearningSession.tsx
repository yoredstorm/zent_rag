// =============================================================================
// Página de sesión de aprendizaje — "ZENT está aprendiendo"
// =============================================================================
// Ruta: /knowledge/sessions/:sessionId. Se llega aquí al subir fuentes o al
// re-sincronizar; la experiencia vive de eventos reales del Knowledge Compiler.
// =============================================================================
import { useParams } from "react-router-dom";

import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { LearningSessionView } from "../../components/knowledgeSession/LearningSessionView";

export default function KnowledgeLearningSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();

  return (
    <KnowledgeLayout>
      {sessionId ? (
        <LearningSessionView sessionId={sessionId} />
      ) : (
        <p className="text-[13px] text-muted">Sesión no encontrada.</p>
      )}
    </KnowledgeLayout>
  );
}
