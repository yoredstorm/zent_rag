import {
  ArrowClockwise,
  CaretDown,
  CaretUp,
  CheckCircle,
  Clock,
  Factory,
  Flask,
  Info,
  Package,
  Plus,
  Prohibit,
  Question,
  RocketLaunch,
  Storefront,
  TestTube,
  WarningCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  Checkbox,
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  Modal,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  SkeletonBlock,
  SuccessInline,
  Textarea,
  type Column,
  type Tone,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Overview = {
  products_total: number;
  products_published: number;
  products_drafts: number;
  tenant_installations: number;
  library: { integrations: number; workflow_templates: number; agents: number };
  palette: {
    integrations: { slug: string; name: string; category: string; status: string }[];
    actions: { action_id: string; display_name: string; integration_slug: string }[];
    workflow_templates: { slug: string; name: string; trigger_type: string }[];
    agents: { id: string; name: string }[];
  };
};

type Product = {
  id: string;
  slug: string;
  name: string;
  short_description: string | null;
  product_type: string;
  version: number;
  status: string;
  category: string;
  pricing: Record<string, unknown>;
  created_at: string | null;
  published_at: string | null;
};

type ProductDetail = Product & {
  included_assets: { kind: string; ref: string; alias?: string }[];
  dependencies: { kind: string; ref: string; requirement: string; alias?: string }[];
  countries: string[];
  pricing: Record<string, unknown>;
  entitlements: Record<string, unknown>;
};

const TYPE_LABEL: Record<string, string> = {
  INTEGRATION: "Integración",
  WORKFLOW_TEMPLATE: "Workflow",
  AGENT_TEMPLATE: "Agente",
  INTELLIGENCE_PACK: "Intelligence Pack",
  BUSINESS_PACK: "Business Pack",
  SEMANTIC_PACK: "Semantic Pack",
  COMPOSITE_PACK: "Composite",
};

/** Ciclo de vida de un producto de la fábrica (mismo vocabulario del backend). */
const PRODUCT_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  DRAFT: { label: "Borrador", tone: "neutral", icon: Question },
  INTERNAL_TEST: { label: "Test interno", tone: "info", icon: Info },
  SECURITY_REVIEW: { label: "Revisión de seguridad", tone: "warn", icon: WarningCircle },
  PRODUCT_REVIEW: { label: "Revisión de producto", tone: "warn", icon: WarningCircle },
  READY: { label: "Listo", tone: "ok", icon: CheckCircle },
  PUBLISHED: { label: "Publicado", tone: "ok", icon: RocketLaunch },
  PAUSED: { label: "Pausado", tone: "warn", icon: Clock },
  DEPRECATED: { label: "Obsoleto", tone: "danger", icon: Prohibit },
  END_OF_LIFE: { label: "Fin de vida", tone: "danger", icon: Prohibit },
};

function ProductStatusBadge({ status }: { status: string }) {
  const meta = PRODUCT_STATUS_META[status] ?? {
    label: status || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

const PRODUCT_COLUMNS: Column<Product>[] = [
  {
    key: "name",
    header: "Producto",
    render: (p) => (
      <span className="block min-w-0">
        <span className="flex items-center gap-2">
          <Storefront size={15} className="shrink-0 text-faint" aria-hidden />
          <span className="truncate text-[13px] font-medium text-text" title={p.name}>
            {p.name}
          </span>
        </span>
        <span className="mt-0.5 block max-w-96 truncate text-xs text-muted" title={p.short_description ?? undefined}>
          {p.short_description || "Sin descripción"}
        </span>
      </span>
    ),
  },
  {
    key: "product_type",
    header: "Tipo",
    hideBelow: "md",
    render: (p) => <span className="text-xs text-muted">{TYPE_LABEL[p.product_type] ?? p.product_type}</span>,
  },
  {
    key: "version",
    header: "Versión",
    align: "right",
    hideBelow: "lg",
    render: (p) => <span className="mono text-xs text-muted tabular-nums">v{p.version}</span>,
  },
  {
    key: "category",
    header: "Categoría",
    hideBelow: "xl",
    render: (p) => <Badge tone="neutral">{p.category}</Badge>,
  },
  {
    key: "pricing",
    header: "Pricing",
    hideBelow: "lg",
    render: (p) => (
      <span className="mono text-xs text-muted">
        {(p.pricing as { model?: string } | undefined)?.model ?? "FREE"}
      </span>
    ),
  },
  {
    key: "status",
    header: "Estado",
    render: (p) => <ProductStatusBadge status={p.status} />,
  },
];

type Tab = "overview" | "products" | "lab";

export default function MarketplaceFactoryPage() {
  const { session } = usePlatformAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<Product | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [impact, setImpact] = useState<{ installations: number; dependent_products: unknown[] } | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mapKey, setMapKey] = useState("legal_name");
  const [mapPath, setMapPath] = useState("razonSocial");
  const [sample, setSample] = useState("{\"razonSocial\": \"ACME SAC\", \"estado\": \"ACTIVO\"}");
  const [normalized, setNormalized] = useState<string>("");

  async function loadOverview() {
    if (!session) return;
    setError("");
    try {
      const data = await platformApi<Overview>("/api/v1/platform/marketplace/overview", {
        token: session.token,
      });
      setOverview(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function loadProducts() {
    if (!session) return;
    try {
      const data = await platformApi<{ products: Product[] }>("/api/v1/platform/marketplace/products", {
        token: session.token,
      });
      setProducts(data.products || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  function openTab(t: Tab) {
    setTab(t);
    setError("");
    setNotice("");
    if (t === "overview") void loadOverview();
    if (t === "products") void loadProducts();
  }

  useEffect(() => {
    void loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function migrateLegacy() {
    if (!session) return;
    setBusy("migrate");
    setError("");
    setNotice("");
    try {
      const r = await platformApi<{ created: number; skipped: string[] }>(
        "/api/v1/platform/marketplace/migrate-legacy",
        { method: "POST", token: session.token, body: "{}" }
      );
      setNotice(`Migración legacy: ${r.created} productos creados.`);
      await loadOverview();
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function openDetail(p: Product) {
    if (!session) return;
    setSelected(p);
    setDetail(null);
    setImpact(null);
    try {
      const [d, imp] = await Promise.all([
        platformApi<ProductDetail>(`/api/v1/platform/marketplace/products/${p.id}`, { token: session.token }),
        platformApi<{ installations: number; dependent_products: unknown[] }>(
          `/api/v1/platform/marketplace/products/${p.id}/impact`,
          { token: session.token }
        ),
      ]);
      setDetail(d);
      setImpact(imp);
      setTab("products");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function transition(status: string) {
    if (!session || !selected) return;
    setBusy(`t-${status}`);
    setError("");
    try {
      await platformApi(`/api/v1/platform/marketplace/products/${selected.id}/transition`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ status }),
      });
      setNotice(`Producto → ${status}.`);
      await openDetail(selected);
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function newVersion() {
    if (!session || !selected) return;
    setBusy("version");
    setError("");
    try {
      await platformApi(`/api/v1/platform/marketplace/products/${selected.id}/versions`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ version: selected.version + 1 }),
      });
      setNotice(`Nueva versión v${selected.version + 1} creada (DRAFT).`);
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function runLab() {
    if (!session) return;
    setBusy("lab");
    setError("");
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(sample);
      } catch {
        setError("Sample JSON inválido.");
        setBusy("");
        return;
      }
      const r = await platformApi<{ normalized: Record<string, unknown> }>(
        "/api/v1/platform/marketplace/test/output-normalizer",
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ output_map: { [mapKey]: mapPath }, sample: parsed }),
        }
      );
      setNormalized(JSON.stringify(r.normalized, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const tabs: [Tab, string, Icon][] = [
    ["overview", "Overview", Factory],
    ["products", "Products", Package],
    ["lab", "Test Lab", TestTube],
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Marketplace Factory"
        subtitle="El Control Center convierte capacidades de plataforma en productos vendibles para los tenants."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <SuccessInline message={notice} />}

      <div className="tabs">
        {tabs.map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            className="tab"
            aria-current={tab === id ? "page" : undefined}
            onClick={() => openTab(id)}
          >
            <Icon size={15} weight={tab === id ? "fill" : "regular"} aria-hidden />
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" &&
        (overview ? (
          <div className="space-y-4" data-testid="factory-overview">
            <MetricGrid className="xl:grid-cols-5">
              <Metric label="Productos" value={overview.products_total} />
              <Metric label="Publicados" value={overview.products_published} size="md" tone="ok" icon={CheckCircle} />
              <Metric label="Borradores" value={overview.products_drafts} size="md" />
              <Metric label="Installs de tenants" value={overview.tenant_installations} size="md" />
              <Metric label="Integraciones en catálogo" value={overview.library.integrations} size="md" />
            </MetricGrid>
            <Panel>
              <div className="panel-body flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-h3">Fábrica de productos</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-muted">
                    {overview.library.workflow_templates} workflow templates · {overview.library.agents} agentes ·{" "}
                    {overview.palette.actions.length} acciones · {overview.palette.agents.length} agentes de paleta
                  </p>
                </div>
                <Button
                  variant="ghost"
                  leadingIcon={ArrowClockwise}
                  loading={busy === "migrate"}
                  disabled={busy !== ""}
                  onClick={() => void migrateLegacy()}
                >
                  {busy === "migrate" ? "Migrando…" : "Migrar legacy (manifests + workflows)"}
                </Button>
              </div>
            </Panel>
          </div>
        ) : (
          <SkeletonBlock rows={4} />
        ))}

      {tab === "products" && (
        <div className="space-y-3" data-testid="factory-products">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <ResultCount shown={products.length} total={products.length} noun="productos" />
            <Button
              variant="primary"
              leadingIcon={Plus}
              onClick={() => setCreating(true)}
            >
              Nuevo producto
            </Button>
          </div>
          <DataTable
            columns={PRODUCT_COLUMNS}
            rows={products}
            rowKey={(p) => p.id}
            caption="Productos de la fábrica"
            stickyHeader
            onRowClick={(p) => void openDetail(p)}
            empty={
              <EmptyState
                icon={Package}
                title="Sin productos todavía"
                body="Crea el primero con el Product Studio: elegís tipo, assets y pricing."
                hint="Los productos nacen en DRAFT y pasan por revisión antes de publicarse."
              />
            }
          />
        </div>
      )}

      {tab === "lab" && (
        <div className="grid gap-4 lg:grid-cols-2 lg:items-start" data-testid="factory-lab">
          <Panel>
            <PanelHeader
              title={
                <span className="flex items-center gap-2">
                  <Flask size={16} className="text-faint" aria-hidden />
                  Output Normalizer
                </span>
              }
              description="Mapea la respuesta del proveedor a un output estable sin llamadas externas."
            />
            <div className="panel-body flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Campo de salida">
                  <Input
                    className="font-mono"
                    value={mapKey}
                    onChange={(e) => setMapKey(e.target.value)}
                    placeholder="legal_name"
                  />
                </Field>
                <Field label="Ruta en la respuesta">
                  <Input
                    className="font-mono"
                    value={mapPath}
                    onChange={(e) => setMapPath(e.target.value)}
                    placeholder="razonSocial"
                  />
                </Field>
              </div>
              <Field label="Sample de respuesta del proveedor (JSON)">
                <Textarea
                  className="font-mono text-xs"
                  rows={5}
                  value={sample}
                  onChange={(e) => setSample(e.target.value)}
                />
              </Field>
              <Button
                variant="primary"
                leadingIcon={TestTube}
                loading={busy === "lab"}
                disabled={busy !== ""}
                onClick={() => void runLab()}
              >
                {busy === "lab" ? "Probando…" : "Probar mapeo"}
              </Button>
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Output normalizado" description="Resultado del último mapeo probado." />
            <div className="panel-body">
              {normalized ? (
                <CodeBlock code={normalized} language="json" maxHeight={320} />
              ) : (
                <p className="rounded-sm border border-border bg-control px-3 py-2.5 font-mono text-xs text-ghost">
                  El resultado aparecerá aquí…
                </p>
              )}
            </div>
          </Panel>
        </div>
      )}

      {creating && (
        <ProductWizard
          palette={overview?.palette}
          onClose={() => setCreating(false)}
          onSaved={async () => {
            setCreating(false);
            setNotice("Producto guardado.");
            await loadProducts();
          }}
        />
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) {
            setSelected(null);
            setDetail(null);
            setImpact(null);
          }
        }}
        title={detail?.name ?? selected?.name ?? "Producto"}
        description={detail?.short_description ?? selected?.short_description ?? undefined}
        width={560}
        footer={
          detail && (
            <>
              <Button
                variant="ghost"
                leadingIcon={CaretDown}
                loading={busy === "version"}
                disabled={busy !== ""}
                onClick={() => void newVersion()}
              >
                Nueva versión (clon)
              </Button>
              {(["READY", "PUBLISHED", "PAUSED"] as const).map((st) => (
                <Button
                  key={st}
                  variant={st === "PUBLISHED" ? "primary" : "ghost"}
                  leadingIcon={st === "PUBLISHED" ? RocketLaunch : st === "READY" ? Factory : undefined}
                  loading={busy === `t-${st}`}
                  disabled={busy !== "" || detail.status === st}
                  onClick={() => void transition(st)}
                >
                  {PRODUCT_STATUS_META[st]?.label ?? st}
                </Button>
              ))}
            </>
          )
        }
      >
        {selected && !detail && (
          <div className="flex flex-col gap-3">
            <SkeletonBlock rows={3} />
            <p className="text-[13px] text-muted">Cargando detalle del producto…</p>
          </div>
        )}
        {detail && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <ProductStatusBadge status={detail.status} />
              <Badge tone="neutral">v{detail.version}</Badge>
              <Badge tone="neutral">{TYPE_LABEL[detail.product_type] ?? detail.product_type}</Badge>
              <Badge tone="neutral">{detail.category}</Badge>
            </div>

            {impact && (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border border-border bg-raised p-3">
                  <p className="stat-label">Instalaciones activas</p>
                  <p className="mt-1.5 text-[22px] leading-none font-semibold text-text tabular-nums">
                    {impact.installations}
                  </p>
                </div>
                <div className="rounded-md border border-border bg-raised p-3">
                  <p className="stat-label">Productos dependientes</p>
                  <p className="mt-1.5 text-[22px] leading-none font-semibold text-text tabular-nums">
                    {impact.dependent_products.length}
                  </p>
                </div>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-md border border-border bg-raised p-3">
                <p className="eyebrow mb-2">Incluye</p>
                <ul className="space-y-1.5">
                  {detail.included_assets.length === 0 && <li className="text-xs text-muted">Sin assets aún</li>}
                  {detail.included_assets.map((a, i) => (
                    <li key={`${a.kind}-${a.ref}-${i}`} className="flex items-start gap-2 text-xs text-text">
                      <CheckCircle size={13} className="mt-0.5 shrink-0 text-accent" aria-hidden />
                      <span className="min-w-0 break-words">
                        <span className="mono text-[11px] text-muted">{a.kind}</span> · {a.ref}
                        {a.alias ? ` (${a.alias})` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-md border border-border bg-raised p-3">
                <p className="eyebrow mb-2">Dependencias</p>
                <ul className="space-y-1.5">
                  {detail.dependencies.length === 0 && <li className="text-xs text-muted">Sin dependencias</li>}
                  {detail.dependencies.map((d, i) => (
                    <li key={`${d.kind}-${d.ref}-${i}`} className="flex items-start gap-2 text-xs text-text">
                      <CaretUp size={12} className="mt-0.5 shrink-0 text-faint" aria-hidden />
                      <span className="min-w-0 break-words">
                        <span className="mono text-[11px] text-muted">{d.kind}</span>:{d.ref} ({d.requirement})
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div>
              <p className="eyebrow mb-2">Pricing</p>
              <CodeBlock code={JSON.stringify(detail.pricing, null, 2)} language="json" maxHeight={220} />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

function ProductWizard({
  palette,
  onClose,
  onSaved,
}: {
  palette: Overview["palette"] | undefined;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { session } = usePlatformAuth();
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [type, setType] = useState("BUSINESS_PACK");
  const [category, setCategory] = useState("operations");
  const [countries, setCountries] = useState("PE");
  const [shortDesc, setShortDesc] = useState("");
  const [integrations, setIntegrations] = useState<string[]>([]);
  const [workflows, setWorkflows] = useState<string[]>([]);
  const [pricingModel, setPricingModel] = useState("FREE");

  async function save() {
    if (!session) return;
    setBusy(true);
    setError("");
    const assets = [
      ...integrations.map((ref) => ({ kind: "integration", ref, alias: ref })),
      ...workflows.map((ref) => ({ kind: "workflow_template", ref, alias: ref })),
    ];
    try {
      await platformApi(
        "/api/v1/platform/marketplace/products",
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({
            slug,
            name,
            short_description: shortDesc,
            product_type: type,
            category,
            countries: countries.split(",").map((c) => c.trim()).filter(Boolean),
            pricing: { model: pricingModel },
            entitlements: {},
            dependencies: [],
            included_assets: assets,
            installation_flow: [],
            status: "DRAFT",
          }),
        }
      );
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  const toggle = (list: string[], set: (v: string[]) => void, item: string) => {
    set(list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  };

  return (
    <Modal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Nuevo producto"
      description={`Paso ${step} de 2 — Product Studio`}
      size="lg"
      footer={
        step === 1 ? (
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              disabled={!name.trim() || !slug.trim()}
              onClick={() => setStep(2)}
            >
              Siguiente: incluye
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" disabled={busy} onClick={() => setStep(1)}>
              ← Volver
            </Button>
            <span className="flex-1" aria-hidden />
            <Button variant="ghost" disabled={busy} onClick={onClose}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              leadingIcon={Plus}
              loading={busy}
              onClick={() => void save()}
            >
              {busy ? "Guardando…" : "Guardar producto"}
            </Button>
          </>
        )
      }
    >
      {error && <ErrorInline>{error}</ErrorInline>}

      {step === 1 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Nombre del producto" className="sm:col-span-2">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Peru Business Verification"
            />
          </Field>
          <Field label="Slug">
            <Input
              className="font-mono"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="peru-business-verification"
            />
          </Field>
          <Field label="Tipo">
            <Select value={type} onChange={(e) => setType(e.target.value)}>
              {Object.entries(TYPE_LABEL).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Categoría">
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="operations"
            />
          </Field>
          <Field label="Países (ISO, coma)" hint="Ej. PE,CL,MX">
            <Input
              className="font-mono"
              value={countries}
              onChange={(e) => setCountries(e.target.value)}
              placeholder="PE,CL,MX"
            />
          </Field>
          <Field label="Descripción corta (what it does)" className="sm:col-span-2">
            <Textarea
              rows={2}
              value={shortDesc}
              onChange={(e) => setShortDesc(e.target.value)}
              placeholder="Verifica un negocio en Perú: SUNAT + workflow + reporte."
            />
          </Field>
        </div>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-4">
          <div>
            <p className="eyebrow mb-2">Integraciones</p>
            <div className="max-h-44 space-y-2 overflow-y-auto rounded-md border border-border bg-raised p-3">
              {(palette?.integrations ?? []).map((i) => (
                <Checkbox
                  key={i.slug}
                  checked={integrations.includes(i.slug)}
                  onCheckedChange={() => toggle(integrations, setIntegrations, i.slug)}
                  label={
                    <span>
                      {i.name} <span className="mono text-[11px] text-faint">({i.slug})</span>
                    </span>
                  }
                />
              ))}
              {(palette?.integrations ?? []).length === 0 && (
                <p className="text-xs text-muted">Sin integraciones en la paleta.</p>
              )}
            </div>
          </div>
          <div>
            <p className="eyebrow mb-2">Workflow templates</p>
            <div className="max-h-44 space-y-2 overflow-y-auto rounded-md border border-border bg-raised p-3">
              {(palette?.workflow_templates ?? []).map((w) => (
                <Checkbox
                  key={w.slug}
                  checked={workflows.includes(w.slug)}
                  onCheckedChange={() => toggle(workflows, setWorkflows, w.slug)}
                  label={
                    <span>
                      {w.name} <span className="mono text-[11px] text-faint">({w.slug})</span>
                    </span>
                  }
                />
              ))}
              {(palette?.workflow_templates ?? []).length === 0 && (
                <p className="text-xs text-muted">Sin workflow templates en la paleta.</p>
              )}
            </div>
          </div>
          <Field label="Pricing model">
            <Select value={pricingModel} onChange={(e) => setPricingModel(e.target.value)}>
              {["FREE", "ONE_TIME", "SUBSCRIPTION", "PER_USE", "BASE_PLUS_USAGE", "PLAN_INCLUDED", "CUSTOM"].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}
    </Modal>
  );
}
