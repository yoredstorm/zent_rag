import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  DataTable,
  EmptyState,
  ErrorInline,
  Input,
  type Column,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import { statusLabelFor, statusToneFor } from "./companyCopy";

type RelationshipRow = {
  id: string;
  from: { id: string; name: string; type: string };
  to: { id: string; name: string; type: string };
  relationship_type: string;
  status: string;
  confidence: number | null;
  confirmed: boolean;
  valid_from: string | null;
  valid_to: string | null;
  observed: boolean;
};

type Relationship = {
  id: string;
  from_entity_id: string;
  to_entity_id: string;
  relationship_type: string;
  status: string;
  confidence: number | null;
  source: string;
  source_ref: string;
  metadata: Record<string, unknown>;
  valid_from: string | null;
  valid_to: string | null;
};

const PAGE_SIZE = 25;

export default function CompanyRelationshipsPage() {
  const { session } = useAuth();
  const [rows, setRows] = useState<RelationshipRow[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(page * PAGE_SIZE),
        });
        if (status) params.set("status", status);
        else params.set("current_only", "true");
        const data = await api<{ items: Relationship[] }>(
          `/api/v1/company-graph/relationships?${params.toString()}`,
          { token: session.token, organizationId: session.organizationId },
        );
        const items = data.items || [];
        const entityIds = new Set<string>();
        items.forEach((item) => {
          entityIds.add(item.from_entity_id);
          entityIds.add(item.to_entity_id);
        });
        const names = new Map<string, { name: string; type: string }>();
        await Promise.all(
          Array.from(entityIds)
            .slice(0, 100)
            .map(async (id) => {
              try {
                const entity = await api<{ canonical_name: string; entity_type: string }>(
                  `/api/v1/company-graph/entities/${id}`,
                  { token: session.token, organizationId: session.organizationId },
                );
                names.set(id, {
                  name: entity.canonical_name,
                  type: entity.entity_type,
                });
              } catch {
                names.set(id, { name: id.slice(0, 8), type: "unknown" });
              }
            }),
        );
        setRows(
          items.map((item) => ({
            id: item.id,
            from: {
              id: item.from_entity_id,
              name: names.get(item.from_entity_id)?.name || "—",
              type: names.get(item.from_entity_id)?.type || "unknown",
            },
            to: {
              id: item.to_entity_id,
              name: names.get(item.to_entity_id)?.name || "—",
              type: names.get(item.to_entity_id)?.type || "unknown",
            },
            relationship_type: item.relationship_type,
            status: item.status,
            confidence: item.confidence,
            confirmed: ["confirmed", "auto_confirmed"].includes(item.status),
            valid_from: item.valid_from,
            valid_to: item.valid_to,
            observed: Boolean(item.metadata?.observed),
          })),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando relaciones");
        setRows([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [session, status, page]);

  const visible = rows.filter((row) => {
    if (!query) return true;
    const needle = query.toLowerCase();
    return (
      row.from.name.toLowerCase().includes(needle) ||
      row.to.name.toLowerCase().includes(needle) ||
      row.relationship_type.toLowerCase().includes(needle)
    );
  });

  const columns: Column<RelationshipRow>[] = [
    {
      key: "from",
      header: "Origen",
      render: (row) => (
        <Link className="underline" to={`/company-intelligence/entity/${row.from.id}`}>
          {row.from.name}
        </Link>
      ),
    },
    {
      key: "type",
      header: "Relación",
      render: (row) => <Badge tone="neutral">{row.relationship_type}</Badge>,
    },
    {
      key: "to",
      header: "Destino",
      render: (row) => (
        <Link className="underline" to={`/company-intelligence/entity/${row.to.id}`}>
          {row.to.name}
        </Link>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (row) => (
        <Badge tone={statusToneFor(row.status)}>{statusLabelFor(row.status)}</Badge>
      ),
    },
    {
      key: "confidence",
      header: "Confianza",
      render: (row) => (
        <span className="text-sm">
          {row.confidence === null ? "—" : `${Math.round(row.confidence * 100)}%`}
        </span>
      ),
    },
    {
      key: "validity",
      header: "Vigencia",
      render: (row) => (
        <span className="text-xs text-muted">
          {row.valid_from ? row.valid_from.slice(0, 10) : "abierta"}
          {row.valid_to ? ` → ${row.valid_to.slice(0, 10)}` : ""}
        </span>
      ),
    },
  ];

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.relationships}
        subtitle="Todas las aristas del grafo con su estado, confianza y vigencia. Las no confirmadas nunca se muestran como definitivas."
      />
      <ErrorInline message={error} />

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mr-2 text-muted">Estado</span>
          <Select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(0);
            }}
            aria-label="Estado"
          >
            <option value="">Actuales (sin deprecadas)</option>
            <option value="discovered">Descubierto</option>
            <option value="suggested">Sugerido</option>
            <option value="confirmed">Confirmado</option>
            <option value="auto_confirmed">Auto-confirmado</option>
            <option value="contradicted">Contradicho</option>
            <option value="stale">Obsoleto</option>
            <option value="deprecated">Deprecado</option>
          </Select>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-muted">Buscar</span>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Buscar relación"
            placeholder="Entidad o tipo de relación…"
          />
        </label>
      </div>

      <Panel>
        {loading ? (
          <SkeletonTable rows={6} cols={6} />
        ) : visible.length === 0 ? (
          <EmptyState
            title="Sin relaciones"
            body="No hay relaciones que cumplan el filtro. Ejecutá descubrimiento para poblarlas."
          />
        ) : (
          <DataTable
            columns={columns}
            rows={visible}
            rowKey={(row) => row.id} caption="Relaciones del Company Graph"
          />
        )}
      </Panel>
    </CompanyIntelligenceLayout>
  );
}
