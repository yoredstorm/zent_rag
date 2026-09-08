import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { PageHeader } from "../../components/ui";
import { PageTabs } from "../../components/PageTabs";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "understood", label: "What Zent Understood" },
  { id: "content", label: "Content" },
  { id: "sync", label: "Sync" },
  { id: "permissions", label: "Permissions" },
  { id: "advanced", label: "Advanced" },
] as const;

function understoodCopy(type: string, managed: boolean): string {
  if (managed || type === "sql") {
    return "Database: entities, fields, relationships, metrics and enums.";
  }
  if (type === "file") {
    return "PDF / documents: topics, sections, entities, definitions, policies and dates.";
  }
  if (type === "csv" || type === "excel") {
    return "Spreadsheet: dataset type, fields, measures and dimensions.";
  }
  if (type === "web") {
    return "Website: pages, topics and products or services.";
  }
  return "Zent extracts business meaning from this source. Internals stay in Advanced.";
}

export default function SourceDetailPage() {
  const { sourceId } = useParams();
  const { session } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("overview");
  const [source, setSource] = useState<Record<string, unknown> | null>(null);
  const [catalog, setCatalog] = useState<Record<string, unknown>[] | null>(null);

  useEffect(() => {
    if (!session || !sourceId) return;
    api<Record<string, unknown>>(`/api/v1/sources/${sourceId}`, {
      token: session.token,
      organizationId: session.organizationId,
    }).then(setSource);
    api<Record<string, unknown>[]>("/api/v1/catalog/sources", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setCatalog)
      .catch(() => setCatalog([]));
  }, [session, sourceId]);

  const config = (source?.config as { managed?: boolean } | undefined) || {};
  const type = String(source?.type || "");

  return (
    <KnowledgeLayout>
      <PageHeader
        title={String(source?.name || "Source")}
        actions={
          <Link to="/knowledge/sources" className="btn btn-secondary">
            All sources
          </Link>
        }
      />
      <PageTabs
        tabs={TABS}
        active={tab}
        onChange={(id) => setTab(id as (typeof TABS)[number]["id"])}
      />
      {tab === "overview" && (
        <dl className="mt-4 space-y-1 text-sm">
          <div>Status: {String(source?.status || "")}</div>
          <div>Last sync: {String(source?.last_sync || "—")}</div>
          <div>Issues: {String(source?.error_count || 0)}</div>
          <div>Usage: {String(source?.document_count || 0)}</div>
          <div>Readiness: {String(source?.status || "—")}</div>
        </dl>
      )}
      {tab === "understood" && (
        <div className="mt-4 space-y-2 text-sm">
          <p>{understoodCopy(type, Boolean(config.managed))}</p>
          <Link to="/knowledge/understanding" className="text-accent underline">
            Open Entendimiento
          </Link>
          {catalog && catalog.length > 0 ? (
            <p className="text-muted">{catalog.length} catalog sources in this workspace.</p>
          ) : null}
        </div>
      )}
      {tab === "content" && (
        <p className="mt-4 text-sm text-muted">Indexed content for this source.</p>
      )}
      {tab === "sync" && (
        <p className="mt-4 text-sm text-muted">
          Last sync: {String(source?.last_sync || "never")}. {String(source?.last_error || "")}
        </p>
      )}
      {tab === "permissions" && (
        <p className="mt-4 text-sm text-muted">Workspace members with knowledge access can use this source.</p>
      )}
      {tab === "advanced" && (
        <p className="mt-4 text-xs text-muted">
          vector collection id, embedding model, chunk size, introspection SQL and AST
          are hidden from the default view.
        </p>
      )}
    </KnowledgeLayout>
  );
}
