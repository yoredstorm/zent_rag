import { CaretDown, Check, type Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Badge, Checkbox, Field, Panel, cn } from "../ui";

const LABEL_CLASS = "text-[13px] font-medium text-text";

/**
 * Campo del panel de ajustes. Envuelve la primitiva `Field`: label real siempre
 * visible, hint y error conectados por `aria-describedby`, control con el id del
 * campo (los inputs del panel usan las primitivas Input/Textarea/Select).
 */
export function AgentField({
  id,
  label,
  hint,
  error,
  required,
  className,
  labelAction,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  /** Acción junto al label (generar, restaurar, ver detalle). */
  labelAction?: ReactNode;
  children: ReactNode;
}) {
  if (!labelAction) {
    return (
      <Field
        id={id}
        label={<span className={LABEL_CLASS}>{label}</span>}
        hint={hint}
        error={error}
        required={required}
        className={className}
      >
        {children}
      </Field>
    );
  }
  return (
    <div className={cn("field", className)}>
      <span className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className={LABEL_CLASS}>
          {label}
          {required && (
            <span className="text-danger" aria-hidden>
              {" "}
              *
            </span>
          )}
        </label>
        {labelAction}
      </span>
      {children}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
      {hint && <p className="field-hint">{hint}</p>}
    </div>
  );
}

/**
 * Sección del estudio dentro de un panel: el título pesa más que el borde, así
 * el panel se lee como una lista de decisiones y no como un formulario largo.
 */
export function AgentSection({
  title,
  hint,
  actions,
  children,
  className,
}: {
  title: string;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("grid gap-3", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold tracking-[-0.01em] text-text">{title}</h3>
          {hint && <p className="mt-0.5 text-xs leading-relaxed text-muted">{hint}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

/**
 * Progressive disclosure dentro de un panel: cerrado resume en una línea lo que
 * hay adentro; abierto muestra el detalle. Sin `<details>` para poder
 * controlarlo (y testearlo) desde el estado del panel.
 */
export function AgentCollapsible({
  id,
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  /** Qué hay adentro cuando está cerrado. */
  summary?: ReactNode;
  open: boolean;
  onToggle: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-3">
      <button
        type="button"
        className="flex w-full cursor-pointer items-start justify-between gap-3 text-left"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => onToggle(!open)}
      >
        <span className="min-w-0">
          <span className="block text-[13px] font-semibold tracking-[-0.01em] text-text">
            {title}
          </span>
          {summary && <span className="mt-0.5 block truncate text-xs text-muted">{summary}</span>}
        </span>
        <CaretDown
          size={14}
          aria-hidden
          className={cn(
            "mt-0.5 shrink-0 text-faint transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>
      {open && <div id={id}>{children}</div>}
    </section>
  );
}

/**
 * Tarjeta seleccionable: una decisión entre pocas. El estado elegido se ve por
 * borde + fondo + check, nunca sólo por color (lleva `aria-pressed`).
 */
export function AgentOptionCard({
  id,
  label,
  hint,
  selected,
  onSelect,
  trailing,
  disabled = false,
  className,
}: {
  id: string;
  label: string;
  hint?: string;
  selected: boolean;
  onSelect: () => void;
  trailing?: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      id={id}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "flex w-full cursor-pointer items-start gap-2.5 rounded-md border bg-raised p-3 text-left",
        "transition-colors duration-150",
        disabled && "pointer-events-none opacity-45",
        selected
          ? "border-accent-line bg-accent-soft/40"
          : "border-border hover:border-border-strong",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-150",
          selected ? "border-accent bg-accent text-accent-fg" : "border-border-strong text-transparent",
        )}
      >
        <Check size={11} weight="bold" />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-text">{label}</span>
        {hint && <span className="mt-0.5 block text-xs leading-relaxed text-muted">{hint}</span>}
      </span>
      {trailing && <span className="ml-auto shrink-0">{trailing}</span>}
    </button>
  );
}

export type AgentToggleOption = {
  key: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

/** Rejilla de interruptores con la primitiva Checkbox (foco visible y aria). */
export function AgentToggleGrid({
  options,
  columns = 2,
  className,
}: {
  options: AgentToggleOption[];
  columns?: 1 | 2;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-x-4 gap-y-2",
        columns === 2 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1",
        className,
      )}
    >
      {options.map((option) => (
        <Checkbox
          key={option.key}
          id={`toggle-${option.key}`}
          checked={option.checked}
          onCheckedChange={option.onChange}
          label={option.label}
          className="items-center"
        />
      ))}
    </div>
  );
}

/** Badge de estado reutilizable del estudio (texto siempre, no sólo color). */
export function AgentStatusBadge({
  active,
  icon,
}: {
  active: boolean;
  icon?: Icon;
}) {
  return (
    <span data-testid="agent-status" className="inline-flex">
      <Badge tone={active ? "ok" : "neutral"} dot icon={icon}>
        {active ? "Activo" : "En pausa"}
      </Badge>
    </span>
  );
}

/**
 * Permiso del agente: nombre en claro, qué implica y el id de la tool.
 * El toggle es la primitiva Checkbox (foco visible y estado por `aria-checked`).
 */
export function AgentToggleCard({
  id,
  label,
  hint,
  tech,
  checked,
  onChange,
  disabled = false,
  disabledHint,
}: {
  id: string;
  label: string;
  hint: string;
  tech: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  disabledHint?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border bg-raised p-3 transition-colors duration-150",
        disabled
          ? "border-border opacity-70"
          : checked
            ? "border-accent-line bg-accent-soft/40"
            : "border-border hover:border-border-strong",
      )}
    >
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        label={<span className="font-medium">{label}</span>}
        hint={hint}
        disabled={disabled}
      />
      <p className="mt-1 pl-[26px] font-mono text-[11px] text-faint">{tech}</p>
      {disabled && disabledHint ? (
        <p className="mt-1 pl-[26px] text-[11px] leading-relaxed text-faint">{disabledHint}</p>
      ) : null}
    </div>
  );
}

/**
 * Progressive disclosure del estudio: el título resume y el detalle aparece
 * solo cuando se pide. Sin `<details>` para mantener el control desde la URL.
 */
export function AgentDisclosure({
  id,
  title,
  hint,
  open,
  onToggle,
  children,
  className,
}: {
  id: string;
  title: string;
  hint?: ReactNode;
  open: boolean;
  onToggle: (open: boolean) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Panel className={className}>
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg px-4 py-3 text-left"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => onToggle(!open)}
      >
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-h3">{title}</span>
          {hint && <span className="text-xs text-muted">{hint}</span>}
        </span>
        <CaretDown
          size={15}
          aria-hidden
          className={cn(
            "shrink-0 text-faint transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div id={id} className="animate-rise border-t border-border p-4">
          {children}
        </div>
      )}
    </Panel>
  );
}
