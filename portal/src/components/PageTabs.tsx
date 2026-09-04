import type { Icon } from "@phosphor-icons/react";

export type TabDef = {
  id: string;
  label: string;
  icon?: Icon;
  disabled?: boolean;
};

export function PageTabs({
  tabs,
  active,
  onChange,
  idPrefix,
}: {
  tabs: readonly TabDef[];
  active: string;
  onChange: (id: string) => void;
  idPrefix?: string;
}) {
  const base = idPrefix || "pagetab";
  return (
    <div className="tabs" role="tablist" aria-label="Secciones">
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`${base}-${tab.id}`}
            aria-selected={selected}
            aria-controls={`${base}-panel-${tab.id}`}
            disabled={tab.disabled}
            className="tab disabled:pointer-events-none disabled:opacity-45"
            onClick={() => onChange(tab.id)}
          >
            {tab.icon && <tab.icon size={15} aria-hidden />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}