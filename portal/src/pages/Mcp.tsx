import { Plugs, ShieldCheck, TerminalWindow } from "@phosphor-icons/react";
import { PageHeader } from "../components/ui";

const TOOLS = [
  { tool: "search_knowledge", perm: "rag:read", desc: "Búsqueda semántica en la knowledge base del tenant (chunks + scores)." },
  { tool: "query_database", perm: "rag:read", desc: "Pregunta NL → SQL read-only validado (guardas del SQL Expert intactas). SQL solo visible con rol admin." },
  { tool: "get_document", perm: "rag:read", desc: "Fetch de chunks por document_id (Qdrant) con verificación estricta de tenant." },
  { tool: "execute_agent", perm: "agents:execute", desc: "Ejecuta un agente configurado (ReAct + allowlist de tools + guardrails + quotas)." },
  { tool: "get_usage", perm: "usage:read", desc: "Agregados de uso de la organización (requests, tokens, latencia, costo)." },
];

export default function McpPage() {
  return (
    <div>
      <PageHeader
        title="MCP"
        subtitle="Model Context Protocol: conecta Zent desde Cursor, Claude Desktop o cualquier cliente MCP mediante Streamable HTTP."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="panel p-5 lg:col-span-2">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
            <TerminalWindow size={15} aria-hidden /> Endpoint
          </h2>
          <p className="mb-3 text-sm text-muted">
            El servidor MCP está montado en la misma API bajo{" "}
            <code className="rounded-xs bg-soft px-1.5 py-0.5 font-mono text-xs text-accent">/mcp</code>,
            transporte <strong className="text-text">Streamable HTTP (stateless)</strong>. Cada request es
            independiente y usa la misma identidad que el REST API.
          </p>
          <div className="rounded-md border border-border bg-soft p-3 font-mono text-xs leading-relaxed">
            <p>POST /mcp</p>
            <p className="mt-1 text-muted">Authorization: Bearer zent_sk_live_...</p>
            <p className="mt-1 text-muted">X-Zent-MCP-Client: &lt;nombre&gt;/&lt;versión&gt;  (opcional, para auditoría)</p>
          </div>
          <p className="mt-3 text-xs text-faint">
            La identidad (tenant/usuario/permisos) se deriva exclusivamente del token validado por el
            TenantMiddleware. La cuota del plan y los rate limits aplican igual que en REST.
          </p>
        </section>

        <section className="panel p-5">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
            <ShieldCheck size={15} aria-hidden /> Seguridad
          </h2>
          <ul className="space-y-2 text-[13px] leading-relaxed text-muted">
            <li>· MCP no es un camino alternativo: auth, cuota y rate limits idénticos a REST.</li>
            <li>· El rol solo puede degradarse (nunca elevarse).</li>
            <li>· Cada tool call queda en audit_logs con latencia, costo y resultado.</li>
            <li>· DNS-rebinding protegido vía allowlist de hosts (RAG_RAG_MCP_ALLOWED_HOSTS).</li>
          </ul>
        </section>
      </div>

      <section className="panel mt-4 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>Permiso</th>
              <th>Descripción</th>
            </tr>
          </thead>
          <tbody>
            {TOOLS.map((t) => (
              <tr key={t.tool}>
                <td className="font-mono text-xs text-accent">{t.tool}</td>
                <td>
                  <span className="badge badge-muted">{t.perm}</span>
                </td>
                <td className="text-sm text-muted">{t.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel mt-4 p-5">
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
          <Plugs size={15} aria-hidden /> Ejemplo (SDK Python)
        </h2>
        <pre className="overflow-x-auto rounded-sm bg-[var(--zent-code-bg)] p-3 font-mono text-xs leading-relaxed">
{`import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    headers = {"Authorization": "Bearer zent_sk_live_..."}
    async with streamable_http_client("http://localhost:8000/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_knowledge", {"query": "política de reembolsos"})
            print(result)

asyncio.run(main())`}
        </pre>
      </section>
    </div>
  );
}