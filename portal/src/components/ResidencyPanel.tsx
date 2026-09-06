import { useEffect, useState } from "react";
import { api, type Session } from "../api";

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
  return (
    <section className="panel mt-4 p-5">
      <h2 className="mb-2 text-sm font-semibold text-text">Data residency</h2>
      <dl className="space-y-1 text-[13px]">
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Región primaria</dt>
          <dd className="mono text-text">{res.primary_region ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Región resuelta</dt>
          <dd className="mono text-text">{res.resolved_region}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Regiones disponibles</dt>
          <dd className="text-right text-text">{res.regions.map((r) => r.code).join(", ") || "—"}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] text-faint">{res.note}</p>
    </section>
  );
}