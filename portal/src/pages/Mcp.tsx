import { Plugs, ShieldCheck, TerminalWindow } from "@phosphor-icons/react";
import McpControlPanel from "../components/McpControlPanel";
import {
  Badge,
  CodeBlock,
  DataTable,
  PageHeader,
  Panel,
  PanelHeader,
  type Column,
} from "../components/ui";

type McpTool = { tool: string; perm: string; desc: string };

const TOOLS: McpTool[] = [
  { tool: "search_knowledge", perm: "rag:read", desc: "Búsqueda semántica en la knowledge base del tenant (chunks + scores)." },
  { tool: "query_database", perm: "rag:read", desc: "Pregunta NL → SQL read-only validado (guardas del SQL Expert intactas). SQL solo visible con rol admin." },
  { tool: "get_document", perm: "rag:read", desc: "Fetch de chunks por document_id (Qdrant) con verificación estricta de tenant." },
  { tool: "execute_agent", perm: "agents:execute", desc: "Ejecuta un agente configurado (ReAct + allowlist de tools + guardrails + quotas)." },
  { tool: "get_usage", perm: "usage:read", desc: "Agregados de uso de la organización (requests, tokens, latencia, costo)." },
];

const COLUMNS: Column<McpTool>[] = [
  {
    key: "tool",
    header: "Tool",
    render: (t) => <span className="mono text-xs text-accent">{t.tool}</span>,
  },
  {
    key: "perm",
    header: "Permiso",
    width: "1%",
    render: (t) => <Badge tone="neutral">{t.perm}</Badge>,
  },
  {
    key: "desc",
    header: "Descripción",
    render: (t) => <span className="text-[13px] leading-relaxed text-muted">{t.desc}</span>,
  },
];

const ENDPOINT = `POST /mcp
Authorization: Bearer zent_sk_live_...
X-Zent-MCP-Client: <nombre>/<versión>  (opcional, para auditoría)`;

const PYTHON_EXAMPLE = `import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    headers = {"Authorization": "Bearer zent_sk_live_..."}
    async with streamable_http_client("http://localhost:8000/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_knowledge", {"query": "política de reembolsos"})
            print(result)


asyncio.run(main())`;

export default function McpPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="MCP"
        subtitle="Model Context Protocol: conecta Zent desde Cursor, Claude Desktop o cualquier cliente MCP mediante Streamable HTTP."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <PanelHeader
            title={
              <span className="flex items-center gap-2">
                <TerminalWindow size={16} className="text-accent" aria-hidden /> Endpoint
              </span>
            }
          />
          <div className="panel-body">
            <p className="prose-measure text-[13px] leading-relaxed text-muted">
              El servidor MCP está montado en la misma API bajo{" "}
              <code className="rounded-xs bg-soft px-1.5 py-0.5 font-mono text-xs text-accent">/mcp</code>,
              transporte <strong className="text-text">Streamable HTTP (stateless)</strong>. Cada request es
              independiente y usa la misma identidad que el REST API.
            </p>
            <CodeBlock code={ENDPOINT} language="http" filename="POST /mcp" maxHeight={200} className="mt-3" />
            <p className="mt-3 text-xs leading-relaxed text-faint">
              La identidad (tenant/usuario/permisos) se deriva exclusivamente del token validado por el
              TenantMiddleware. La cuota del plan y los rate limits aplican igual que en REST.
            </p>
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title={
              <span className="flex items-center gap-2">
                <ShieldCheck size={16} className="text-accent" aria-hidden /> Seguridad
              </span>
            }
          />
          <ul className="flex flex-col gap-2 p-4 text-[13px] leading-relaxed text-muted">
            <li>· MCP no es un camino alternativo: auth, cuota y rate limits idénticos a REST.</li>
            <li>· El rol solo puede degradarse (nunca elevarse).</li>
            <li>· Cada tool call queda en audit_logs con latencia, costo y resultado.</li>
            <li>· DNS-rebinding protegido vía allowlist de hosts (RAG_RAG_MCP_ALLOWED_HOSTS).</li>
          </ul>
        </Panel>
      </div>

      <DataTable
        caption="Tools expuestos por el servidor MCP"
        columns={COLUMNS}
        rows={TOOLS}
        rowKey={(t) => t.tool}
      />

      <Panel>
        <PanelHeader
          title={
            <span className="flex items-center gap-2">
              <Plugs size={16} className="text-accent" aria-hidden /> Ejemplo (SDK Python)
            </span>
          }
        />
        <div className="panel-body">
          <CodeBlock code={PYTHON_EXAMPLE} language="python" filename="mcp_client.py" />
        </div>
      </Panel>

      <McpControlPanel />
    </div>
  );
}
