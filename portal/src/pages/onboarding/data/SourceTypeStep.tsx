import {
  CloudArrowUp,
  Database,
  FileText,
  Globe,
  Plugs,
  Table,
  FolderSimple,
} from "@phosphor-icons/react";
import { ComingSoonBadge } from "../../../components/ComingSoon";
import { Link } from "react-router-dom";
import type { OnboardingKind } from "./types";

const CARDS: Array<{
  kind: OnboardingKind | null;
  icon: typeof Database;
  title: string;
  body: string;
  soon?: boolean;
  href?: string;
}> = [
  {
    kind: "database",
    icon: Database,
    title: "Base de datos",
    body: "Conecta tu ERP, sistema de ventas o base empresarial.",
  },
  {
    kind: "documents",
    icon: FileText,
    title: "Documentos",
    body: "Contratos, políticas y manuales. Zent extrae partes, fechas, montos y obligaciones.",
  },
  {
    kind: "spreadsheets",
    icon: Table,
    title: "Hojas de cálculo",
    body: "Importa Excel o CSV. Zent mapea columnas a conceptos de negocio.",
  },
  {
    kind: "drive",
    icon: FolderSimple,
    title: "Nube",
    body: "Sincroniza una carpeta compartida de Google Drive.",
  },
  {
    kind: "website",
    icon: Globe,
    title: "Sitio web",
    body: "Permite que Zent entienda contenido de tu sitio.",
  },
  {
    kind: "api",
    icon: Plugs,
    title: "API",
    body: "Conecta sistemas externos.",
  },
  {
    kind: null,
    icon: Database,
    title: "Crear una base",
    body: "Crea una nueva base para tu negocio sin configurar servidores.",
    href: "/knowledge/database",
  },
  {
    kind: null,
    icon: CloudArrowUp,
    title: "Almacenamiento S3",
    body: "Conecta un bucket compatible con S3.",
    soon: true,
  },
  {
    kind: null,
    icon: Globe,
    title: "Sitemap / crawl",
    body: "Indexa un sitio completo a partir del sitemap.",
    soon: true,
  },
  {
    kind: null,
    icon: Plugs,
    title: "GraphQL",
    body: "Ingesta de APIs GraphQL.",
    soon: true,
  },
];

export function SourceTypeStep({
  onSelect,
}: {
  onSelect: (kind: OnboardingKind) => void;
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-text">¿Qué quieres conectar?</h2>
      <p className="mt-1 text-sm text-muted">
        Zent te guía paso a paso. No hace falta saber de conectores ni de SQL.
      </p>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {CARDS.map((card) => {
          const Icon = card.icon;
          if (card.href) {
            return (
              <Link
                key={card.title}
                to={card.href}
                className="panel flex flex-col gap-2 p-5 text-left transition-colors hover:border-accent"
              >
                <Icon size={22} className="text-accent" aria-hidden />
                <h3 className="text-sm font-semibold text-text">{card.title}</h3>
                <p className="text-[13px] leading-relaxed text-muted">{card.body}</p>
              </Link>
            );
          }
          if (card.soon || !card.kind) {
            return (
              <div
                key={card.title}
                className="panel flex flex-col gap-2 p-5 opacity-80"
              >
                <div className="flex items-center justify-between">
                  <Icon size={22} className="text-faint" aria-hidden />
                  <ComingSoonBadge />
                </div>
                <h3 className="text-sm font-semibold text-text">{card.title}</h3>
                <p className="text-[13px] leading-relaxed text-muted">{card.body}</p>
              </div>
            );
          }
          return (
            <button
              key={card.kind}
              type="button"
              data-testid={`source-kind-${card.kind}`}
              className="panel flex flex-col gap-2 p-5 text-left transition-colors hover:border-accent"
              onClick={() => onSelect(card.kind as OnboardingKind)}
            >
              <Icon size={22} className="text-accent" aria-hidden />
              <h3 className="text-sm font-semibold text-text">{card.title}</h3>
              <p className="text-[13px] leading-relaxed text-muted">{card.body}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
