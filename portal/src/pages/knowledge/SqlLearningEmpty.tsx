import { Database } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { EmptyState } from "../../components/ui";
import { COPY } from "./knowledgeCopy";

export function SqlLearningEmpty({ fileCount }: { fileCount: number }) {
  return (
    <div className="panel" data-testid="sql-learning-empty">
      <EmptyState
        icon={Database}
        title={COPY.sqlEmptyTitle}
        body={COPY.sqlEmptyBody(fileCount)}
        action={
          <Link className="btn btn-primary min-h-9" to="/knowledge/sources">
            {COPY.goToSources}
          </Link>
        }
      />
    </div>
  );
}
