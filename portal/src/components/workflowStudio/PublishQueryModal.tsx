/**
 * P19-03b — publicar una consulta desde una tabla del conector.
 * No escribe SQL: descubre tabla/columnas y crea el plan en el servidor.
 */
import { useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Button, Field, Modal, Select } from "../ui";

type Connector = { id: string; name: string; type: string; status: string };
type Table = {
  name: string;
  schema: string;
  is_view: boolean;
  columns: { name: string; data_type: string; is_primary_key: boolean }[];
};

type PublishedPlan = {
  binding_ref: string;
  capability_ref: string;
  resource_ref: string;
  operation: string;
  projection: string[];
  parameters: { name: string; field: string; operator: string; type: string; required: boolean }[];
  max_rows: number;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPublished: (plan: PublishedPlan) => void;
};

export function PublishQueryModal({ open, onOpenChange, onPublished }: Props) {
  const { session } = useAuth();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [connectorId, setConnectorId] = useState("");
  const [tables, setTables] = useState<Table[]>([]);
  const [resource, setResource] = useState("");
  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [keyColumn, setKeyColumn] = useState("");
  const [operation, setOperation] = useState("get_one");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedTable = useMemo(
    () => tables.find((table) => `${table.schema}.${table.name}` === resource) ?? null,
    [tables, resource],
  );

  async function loadConnectors() {
    if (!session || connectors.length > 0) return;
    try {
      const data = await api<{ connectors: Connector[] }>("/api/v1/connectors", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setConnectors(data.connectors.filter((item) => item.type === "postgres"));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "No pude cargar conectores.");
    }
  }

  async function discover() {
    if (!session || !connectorId) return;
    setLoading(true);
    setError("");
    try {
      const data = await api<{ tables: Table[] }>(
        `/api/v1/connectors/${connectorId}/discover`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
        },
      );
      setTables(data.tables ?? []);
      setResource("");
      setSelectedColumns([]);
      setKeyColumn("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "No pude descubrir tablas.");
    } finally {
      setLoading(false);
    }
  }

  function chooseTable(value: string) {
    setResource(value);
    setSelectedColumns([]);
    setKeyColumn("");
  }

  async function publish() {
    if (!session || !connectorId || !resource || selectedColumns.length === 0) return;
    setLoading(true);
    setError("");
    try {
      const published = await api<PublishedPlan>("/api/v1/workflows/data-query/plans", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          connector_ref: `connector:${connectorId}`,
          resource_ref: resource,
          operation,
          projection: selectedColumns,
          parameter:
            keyColumn && operation !== "count"
              ? {
                  name: keyColumn,
                  field: keyColumn,
                  operator: "eq",
                  type: "string",
                  required: true,
                }
              : null,
          max_rows: operation === "get_one" ? 1 : 50,
          label: selectedTable ? `${selectedTable.name}` : resource,
        }),
      });
      onPublished(published);
      onOpenChange(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "No pude publicar la consulta.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Publicar una consulta"
      description="Elige una tabla autorizada del conector. No escribes SQL."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={publish} disabled={!resource || selectedColumns.length === 0 || loading}>
            {loading ? "Publicando…" : "Publicar consulta"}
          </Button>
        </>
      }
    >
      <div className="space-y-3" onFocus={loadConnectors}>
        <Field label="Conexión">
          <Select
            value={connectorId}
            onChange={(event) => {
              setConnectorId(event.target.value);
              setTables([]);
            }}
            onFocus={loadConnectors}
          >
            <option value="">Elige un conector.</option>
            {connectors.map((connector) => (
              <option key={connector.id} value={connector.id}>
                {connector.name}
              </option>
            ))}
          </Select>
        </Field>
        <Button variant="secondary" size="sm" onClick={discover} disabled={!connectorId || loading}>
          Descubrir tablas
        </Button>
        {tables.length > 0 && (
          <Field label="Tabla o vista">
            <Select value={resource} onChange={(event) => chooseTable(event.target.value)}>
              <option value="">Elige una tabla.</option>
              {tables.map((table) => (
                <option key={`${table.schema}.${table.name}`} value={`${table.schema}.${table.name}`}>
                  {table.schema}.{table.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {selectedTable && (
          <>
            <Field label="Operación">
              <Select value={operation} onChange={(event) => setOperation(event.target.value)}>
                <option value="get_one">Buscar un registro</option>
                <option value="list">Listar</option>
                <option value="count">Contar</option>
              </Select>
            </Field>
            <Field label="Columna de búsqueda" hint="Será el parámetro del nodo.">
              <Select value={keyColumn} onChange={(event) => setKeyColumn(event.target.value)}>
                <option value="">Sin parámetro</option>
                {selectedTable.columns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name} ({column.data_type})
                  </option>
                ))}
              </Select>
            </Field>
            <div>
              <p className="eyebrow mb-1">Columnas que devuelve</p>
              <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                {selectedTable.columns.map((column) => (
                  <label key={column.name} className="flex items-center gap-2 text-[12px] text-text">
                    <input
                      type="checkbox"
                      checked={selectedColumns.includes(column.name)}
                      onChange={(event) =>
                        setSelectedColumns((current) =>
                          event.target.checked
                            ? [...current, column.name]
                            : current.filter((item) => item !== column.name),
                        )
                      }
                    />
                    {column.name}
                    <span className="text-[10px] text-faint">{column.data_type}</span>
                  </label>
                ))}
              </div>
            </div>
          </>
        )}
        {error && <p className="text-[12px] text-danger">{error}</p>}
      </div>
    </Modal>
  );
}
