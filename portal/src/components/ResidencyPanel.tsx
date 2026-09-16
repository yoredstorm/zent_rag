import { WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api, type Session } from "../api";
import { Badge, KeyValue, Panel, PanelHeader, StatusBadge } from "./ui";

type Residency = {
  primary_region: string | null;
  resolved_region: string;
  regions: { code: string; name?: string; status?: string }[];
  note: string;
};

/** FASE 03 (S19): data residency — visualización honesta de la resolución. */
export default function ResidencyPanel({ session }: { session: Session | null }) {
  const [res, setRes] = useState<Residency | null>(null);

  useEffect(() => {
    if (!session) return;
    api<Residency>("/api/v1/organizations/residency", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setRes)
      .catch(() => undefined);
  }, [session]);

  if (!res) return null;

  const declared = res.primary_region;
  const applied = res.resolved_region;
  const overridden = Boolean(declared) && declared !== applied;

  return (
    <Panel className="mt-4">
      <PanelHeader
        title="Data residency"
        description="Región declarada, región aplicada y regiones disponibles para esta organización."
        actions={
          overridden ? (
            <Badge tone="warn" icon={WarningCircle}>
              Se aplica {applied}
            </Badge>
          ) : undefined
        }
      />
      <div className="panel-body">
        <KeyValue
          columns={2}
          items={[
            {
              key: overridden ? "Región declarada (no aplicada)" : "Región primaria",
              value: declared ?? "Sin declarar",
              mono: Boolean(declared),
            },
            { key: "Región aplicada", value: applied, mono: true },
          ]}
        />
        <div className="mt-4">
          <p className="eyebrow mb-2">Regiones disponibles ({res.regions.length})</p>
          {res.regions.length === 0 ? (
            <p className="text-[13px] leading-relaxed text-muted">
              La organización todavía no tiene regiones habilitadas. La plataforma resuelve una por defecto.
            </p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {res.regions.map((r) => (
                <li key={r.code}>
                  <StatusBadge status={r.status ?? ""} label={r.name ? `${r.code} · ${r.name}` : r.code} />
                </li>
              ))}
            </ul>
          )}
        </div>
        {res.note && <p className="mt-3 text-xs leading-relaxed text-faint">{res.note}</p>}
      </div>
    </Panel>
  );
}
