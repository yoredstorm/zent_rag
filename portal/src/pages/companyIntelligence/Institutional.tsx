import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import { entityTypeLabel, statusLabelFor, statusToneFor } from "./companyCopy";

type Person = { id: string; display_name: string; entity_type: string; status: string };
type Owner = {
  owner_id: string;
  owner: string;
  owner_type: string;
  relationship_type: string;
  status: string;
};
type Ownership = { process_id: string; process: string; owners: Owner[] };

type Institutional = {
  people: Person[];
  roles: Person[];
  teams: Person[];
  process_ownership: Ownership[];
  processes_without_owner: string[];
};

export default function CompanyInstitutionalPage() {
  const { session } = useAuth();
  const [data, setData] = useState<Institutional | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        setData(
          await api<Institutional>("/api/v1/company-intelligence/institutional", {
            token: session.token,
            organizationId: session.organizationId,
          }),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando personas y equipos");
        setData(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const group = (title: string, items: Person[], groupName: string) => (
    <Panel>
      <PanelHeader
        title={title}
        description={`Derivado de relaciones explícitas del grafo (${entityTypeLabel(groupName)})`}
      />
      {items.length === 0 ? (
        <p className="text-sm text-muted">Sin registros.</p>
      ) : (
        <ul className="flex flex-wrap gap-2 text-sm" data-testid={`institutional-${groupName}`}>
          {items.map((item) => (
            <li key={item.id}>
              <Link
                className="badge badge-muted"
                to={`/company-intelligence/entity/${item.id}`}
              >
                {item.display_name}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.people}
        subtitle="Quién responde por qué. Se calcula desde relaciones OWNS y GOVERNED_BY, no desde supuestos."
      />
      <ErrorInline message={error} />

      {loading && (
        <Panel>
          <SkeletonBlock rows={3} />
        </Panel>
      )}

      {!loading && data && (
        <div className="space-y-4">
          {group("Personas", data.people, "person")}
          {group("Roles", data.roles, "role")}
          {group("Equipos", data.teams, "team")}

          <Panel>
            <PanelHeader title="Responsables por proceso" />
            {data.process_ownership.length === 0 ? (
              <EmptyState
                title="Sin procesos registrados"
                body="Cuando existan procesos con relación OWNS, aparecen acá."
              />
            ) : (
              <ul className="space-y-2 text-sm" data-testid="process-ownership">
                {data.process_ownership.map((item) => (
                  <li key={item.process_id} className="flex flex-wrap items-center gap-2">
                    <Link
                      className="underline"
                      to={`/company-intelligence/entity/${item.process_id}`}
                    >
                      {item.process}
                    </Link>
                    {item.owners.length === 0 ? (
                      <Badge tone="warn">Sin responsable</Badge>
                    ) : (
                      item.owners.map((owner) => (
                        <span key={`${item.process_id}-${owner.owner_id}`}>
                          {owner.owner}{" "}
                          <Badge tone={statusToneFor(owner.status)}>
                            {statusLabelFor(owner.status)}
                          </Badge>
                        </span>
                      ))
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {data.processes_without_owner.length > 0 && (
            <Panel>
              <PanelHeader
                title="Procesos sin responsable"
                description="Candidatos a hueco de conocimiento institucional"
              />
              <div className="flex flex-wrap gap-2">
                {data.processes_without_owner.map((name) => (
                  <Badge key={name} tone="warn">
                    {name}
                  </Badge>
                ))}
              </div>
            </Panel>
          )}
        </div>
      )}
    </CompanyIntelligenceLayout>
  );
}
