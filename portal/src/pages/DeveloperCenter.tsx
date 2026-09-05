import { Code, ListBullets, Terminal } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatusBadge,
} from "../components/ui";

type ApiLog = {
  id: string;
  deployment_id: string | null;
  agent_id: string | null;
  request_id: string;
  endpoint: string;
  method: string;
  status: number;
  latency_ms: number | null;
  tokens: number;
  cost: number | null;
  api_key_id: string | null;
  error: string | null;
  created_at: string;
};

type Deployment = {
  id: string;
  slug: string;
  status: string;
  endpoint: string | null;
};

type SnippetEntry = { label: string; code: string | ((slug: string) => string) };

const SNIPPETS: Record<string, SnippetEntry> = {
  curl: {
    label: "cURL",
    code: (slug: string) => `curl -X POST https://api.zent.example/api/v1/deployments/${slug}/query \\
  -H "Authorization: Bearer zent_sk_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"input": "¿Cuánto stock queda del producto ABC?"}'`,
  },
  python: {
    label: "Python",
    code: (slug: string) => `import requests

resp = requests.post(
    f"https://api.zent.example/api/v1/deployments/${slug}/query",
    headers={"Authorization": "Bearer zent_sk_live_..."},
    json={"input": "¿Cuánto stock queda del producto ABC?"},
)
print(resp.json()["answer"])`,
  },
  javascript: {
    label: "JavaScript",
    code: (slug: string) => `const resp = await fetch(
  "https://api.zent.example/api/v1/deployments/${slug}/query",
  {
    method: "POST",
    headers: {
      Authorization: "Bearer zent_sk_live_...",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input: "¿Cuánto stock queda del producto ABC?" }),
  }
);
console.log(await resp.json());`,
  },
  csharp: {
    label: "C#",
    code: (slug: string) => `using var client = new HttpClient();
client.DefaultRequestHeaders.Authorization =
    new AuthenticationHeaderValue("Bearer", "zent_sk_live_...");
var payload = new { input = "¿Cuánto stock queda del producto ABC?" };
var resp = await client.PostAsJsonAsync(
    "https://api.zent.example/api/v1/deployments/${slug}/query", payload);
Console.WriteLine(await resp.Content.ReadAsStringAsync());`,
  },
  java: {
    label: "Java",
    code: (slug: string) => `HttpRequest req = HttpRequest.newBuilder()
    .uri(URI.create("https://api.zent.example/api/v1/deployments/${slug}/query"))
    .header("Authorization", "Bearer zent_sk_live_...")
    .header("Content-Type", "application/json")
    .POST(BodyPublishers.ofString(
        "{\\"input\\":\\"¿Cuánto stock queda del producto ABC?\\"}"))
    .build();
var resp = HttpClient.newHttpClient().send(req, BodyHandlers.ofString());
System.out.println(resp.body());`,
  },
  php: {
    label: "PHP",
    code: (slug: string) => `<?php
$resp = file_get_contents(
    "https://api.zent.example/api/v1/deployments/${slug}/query",
    false,
    stream_context_create(["http" => [
        "method" => "POST",
        "header" => "Authorization: Bearer zent_sk_live_...\\r\\nContent-Type: application/json",
        "content" => json_encode(["input" => "¿Cuánto stock queda del producto ABC?"]),
    ]])
);
echo $resp;`,
  },
};

const TABS = ["Endpoints", "Logs", "Sandbox"] as const;
type Tab = (typeof TABS)[number];

export default function DeveloperCenter() {
  const { session } = useAuth();
  const [tab, setTab] = useState<Tab>("Endpoints");
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [logs, setLogs] = useState<ApiLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedSlug, setSelectedSlug] = useState("");
  const [lang, setLang] = useState("curl");

  // Sandbox
  const [sandboxKey, setSandboxKey] = useState("");
  const [sandboxInput, setSandboxInput] = useState("¿Cuánto stock queda?");
  const [sandboxResult, setSandboxResult] = useState("");
  const [sandboxBusy, setSandboxBusy] = useState(false);

  async function loadDeployments() {
    if (!session) return;
    try {
      const d = await api<{ deployments: Deployment[] }>("/api/v1/deployments", {
        token: session.token,
        organizationId: session.organizationId,
      });
      const healthy = (d.deployments || []).filter((x) => x.status === "healthy");
      setDeployments(healthy);
      if (healthy.length && !selectedSlug) setSelectedSlug(healthy[0].slug);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  async function loadLogs() {
    if (!session) return;
    try {
      const d = await api<{ logs: ApiLog[] }>("/api/v1/deployments/logs", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setLogs(d.logs || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  useEffect(() => {
    void loadDeployments();
    void loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (tab === "Logs") void loadLogs();
  }, [tab, session]);

  async function runSandbox() {
    if (!session || !selectedSlug) return;
    setSandboxBusy(true);
    setSandboxResult("");
    try {
      const res = await fetch(`/api/v1/deployments/${selectedSlug}/query`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${sandboxKey || session.token}`,
          "Content-Type": "application/json",
          "X-Organization-Id": session.organizationId,
        },
        body: JSON.stringify({ input: sandboxInput }),
      });
      const text = await res.text();
      setSandboxResult(`${res.status}\n${text}`);
    } catch (e) {
      setSandboxResult(e instanceof Error ? e.message : "Error");
    } finally {
      setSandboxBusy(false);
    }
  }

  const entry = selectedSlug ? SNIPPETS[lang] : undefined;
  const snippet = entry ? (typeof entry.code === "function" ? entry.code(selectedSlug) : entry.code) : "";

  return (
    <div>
      <PageHeader
        title="Developer Center"
        subtitle="Consume tus agentes desde ERP/CRM/WMS: API pública, logs y sandbox."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      <div className="mb-4 flex flex-wrap gap-1" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`btn min-h-9 text-xs ${tab === t ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Endpoints" && (
        <div className="space-y-4">
          {loading ? (
            <SkeletonBlock className="h-40" />
          ) : deployments.length === 0 ? (
            <div className="panel">
              <EmptyState
                icon={Terminal}
                title="Sin deployments healthy"
                body="Despliega un agente a production para obtener su endpoint público."
              />
            </div>
          ) : (
            <>
              <div className="panel">
                <label className="flex flex-col gap-1 text-xs text-muted">
                  Deployment (healthy)
                  <select
                    className="input max-w-md"
                    value={selectedSlug}
                    onChange={(e) => setSelectedSlug(e.target.value)}
                  >
                    {deployments.map((d) => (
                      <option key={d.id} value={d.slug}>
                        {d.slug}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="mt-3 font-mono text-xs text-faint">
                  POST /api/v1/deployments/{selectedSlug || "…"}/query
                </p>
              </div>
              <div className="panel">
                <div className="mb-2 flex flex-wrap gap-1">
                  {Object.entries(SNIPPETS).map(([key, info]) => (
                    <button
                      key={key}
                      type="button"
                      className={`btn min-h-8 text-xs ${lang === key ? "btn-primary" : "btn-ghost"}`}
                      onClick={() => setLang(key)}
                    >
                      {info.label}
                    </button>
                  ))}
                </div>
                <pre className="overflow-x-auto rounded-md bg-soft p-3 font-mono text-xs leading-relaxed text-text">
                  <Code size={14} className="mb-1 text-faint" aria-hidden />
                  {snippet}
                </pre>
              </div>
            </>
          )}
        </div>
      )}

      {tab === "Logs" && (
        <div className="panel overflow-x-auto">
          {logs.length === 0 ? (
            <EmptyState icon={ListBullets} title="Sin llamadas" body="Aún no hay llamadas a la API pública." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Endpoint</th>
                  <th>Status</th>
                  <th>Latencia</th>
                  <th>Tokens</th>
                  <th>Costo</th>
                  <th>Key</th>
                  <th>Fecha</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id}>
                    <td className="font-mono text-xs">{l.request_id.slice(0, 8)}</td>
                    <td className="font-mono text-xs text-muted">{l.endpoint}</td>
                    <td>
                      <StatusBadge status={l.status === 200 ? "healthy" : "failed"} />
                    </td>
                    <td className="text-xs text-muted">
                      {l.latency_ms != null ? `${l.latency_ms.toFixed(0)}ms` : "—"}
                    </td>
                    <td className="text-xs text-muted">{l.tokens}</td>
                    <td className="text-xs text-muted">
                      {l.cost != null ? `$${l.cost.toFixed(5)}` : "—"}
                    </td>
                    <td className="font-mono text-xs text-faint">
                      {l.api_key_id ? l.api_key_id.slice(0, 8) : "—"}
                    </td>
                    <td className="text-xs text-faint">
                      {new Date(l.created_at).toLocaleString("es-PE")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Sandbox" && (
        <div className="panel space-y-3">
          <label className="flex flex-col gap-1 text-xs text-muted">
            Deployment
            <select
              className="input max-w-md"
              value={selectedSlug}
              onChange={(e) => setSelectedSlug(e.target.value)}
            >
              {deployments.map((d) => (
                <option key={d.id} value={d.slug}>
                  {d.slug}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            API key (vacío = tu sesión)
            <input
              className="input"
              value={sandboxKey}
              onChange={(e) => setSandboxKey(e.target.value)}
              placeholder="zent_sk_live_..."
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            Input
            <textarea
              className="input min-h-20"
              value={sandboxInput}
              onChange={(e) => setSandboxInput(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn btn-primary min-h-10"
            disabled={sandboxBusy || !selectedSlug}
            onClick={() => void runSandbox()}
          >
            {sandboxBusy ? "Consultando…" : "Probar"}
          </button>
          {sandboxResult && (
            <pre className="overflow-x-auto rounded-md bg-soft p-3 font-mono text-xs whitespace-pre-wrap text-text">
              {sandboxResult}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}