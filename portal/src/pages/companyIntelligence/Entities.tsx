import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  Button,
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
import { COMPANY_HEADINGS, COMPANY_LIST_TYPES } from "../../lib/companyNav";
import { fmtNum } from "../../lib/format";
import { COPY, entityTypeLabel, statusLabelFor, statusToneFor } from "./companyCopy";

type EntityView = {
  id: string;
  entity_type: string;
  canonical_name: string;
  display_name: string;
  domain: string;
  status: string;
  confidence: number | null;
  authority_level: string | null;
  aliases: string[];
  last_observed_at: string;
};

const SECTION_BY_PATH: Record<string, string> = {
  "/company-intelligence/concepts": "concepts",
  "/company-intelligence/processes": "processes",
  "/company-intelligence/systems": "systems",
  "/company-intelligence/data": "data",
  "/company-intelligence/rules": "rules",
  "/company-intelligence/events": "events",
};

const PAGE_SIZE = 25;

export default function CompanyEntitiesPage() {
  const { session } = useAuth();
  const { pathname } = useLocation();
  const section = SECTION_BY_PATH[pathname] || "concepts";
  const types = useMemo(() => COMPANY_LIST_TYPES[section] || [], [section]);
  const [entityType, setEntityType] = useState(types[0] || "");
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("");
  const [domains, setDomains] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<EntityView[]>([]);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setEntityType(types[0] || "");
    setPage(0);
  }, [section, types]);

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const data = await api<{ items: Array<{ domain: string }> }>(
          "/api/v1/company-intelligence/domains",
          { token: session.token, organizationId: session.organizationId },
        );
        setDomains((data.items || []).map((item) => item.domain));
      } catch {
        setDomains([]);
      }
    })();
  }, [session]);

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
        if (entityType) params.set("entity_type", entityType);
        if (query) params.set("q", query);
        if (domain) params.set("domain", domain);
        if (status) params.set("status", status);
        const data = await api<{ items: EntityView[] }>(
          `/api/v1/company-intelligence/entities?${params.toString()}`,
          { token: session.token, organizationId: session.organizationId },
        );
        setItems(data.items || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando entidades");
        setItems([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [session, entityType, query, domain, status, page]);

  const columns: Column<EntityView>[] = [
    {
      key: "name",
      header: "Entidad",
      render: (row) => (
        <div>
          <Link
            className="underline"
            to={
              row.entity_type === "process" || row.entity_type === "workflow"
                ? `/company-intelligence/entity/${row.id}?tab=process`
                : `/company-intelligence/entity/${row.id}`
            }
          >
            {row.display_name}
          </Link>
          {row.aliases.length > 0 && (
            <p className="text-xs text-muted">{row.aliases.slice(0, 3).join(", ")}</p>
          )}
        </div>
      ),
    },
    {
      key: "type",
      header: "Tipo",
      render: (row) => <Badge tone="neutral">{entityTypeLabel(row.entity_type)}</Badge>,
    },
    {
      key: "status",
      header: "Estado",
      render: (row) => (
        <Badge tone={statusToneFor(row.status)}>{statusLabelFor(row.status)}</Badge>
      ),
    },
    {
      key: "domain",
      header: "Dominio",
      render: (row) => <span className="text-sm text-muted">{row.domain}</span>,
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
  ];

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS[section]}
        subtitle="Entidades registradas en el Company Graph con su estado y confianza."
      />

      <ErrorInline message={error} />

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mr-2 text-muted">Tipo</span>
          <Select
            value={entityType}
            onChange={(event) => {
              setEntityType(event.target.value);
              setPage(0);
            }}
            aria-label="Tipo de entidad"
          >
            {types.map((type) => (
              <option key={type} value={type}>
                {entityTypeLabel(type)}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-muted">Dominio</span>
          <Select
            value={domain}
            onChange={(event) => {
              setDomain(event.target.value);
              setPage(0);
            }}
            aria-label="Dominio"
          >
            <option value="">Todos</option>
            {domains.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </label>
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
            <option value="">Todos</option>
            <option value="confirmed">Confirmado</option>
            <option value="auto_confirmed">Auto-confirmado</option>
            <option value="supported">Con respaldo</option>
            <option value="discovered">Descubierto</option>
            <option value="contradicted">Contradicho</option>
            <option value="stale">Obsoleto</option>
          </Select>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-muted">Buscar</span>
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(0);
            }}
            aria-label="Buscar entidad"
            placeholder="Nombre o alias…"
          />
        </label>
      </div>

      <Panel>
        {loading ? (
          <SkeletonTable rows={6} cols={5} />
        ) : items.length === 0 ? (
          <EmptyState title="Sin entidades" body={COPY.emptySearch} />
        ) : (
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(row) => row.id} caption="Entidades del Company Graph"
          />
        )}
        <div className="mt-3 flex items-center justify-between text-sm">
          <span className="text-muted">
            Página {page + 1} · {fmtNum(items.length)} entidades
          </span>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              disabled={page === 0}
              onClick={() => setPage((value) => Math.max(0, value - 1))}
            >
              Anterior
            </Button>
            <Button
              variant="ghost"
              disabled={items.length < PAGE_SIZE}
              onClick={() => setPage((value) => value + 1)}
            >
              Siguiente
            </Button>
          </div>
        </div>
      </Panel>
    </CompanyIntelligenceLayout>
  );
}
