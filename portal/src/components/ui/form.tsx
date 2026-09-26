import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { Check, CircleNotch, Eye, EyeSlash, type Icon } from "@phosphor-icons/react";
import {
  createContext,
  useContext,
  useId,
  useState,
  type ComponentPropsWithoutRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "./cn";
import { CheckCircle, WarningCircle } from "@phosphor-icons/react";

/* ------------------------------------------------------------------ */
/* Field: label + control + hint + error con aria conectado            */
/* ------------------------------------------------------------------ */

type FieldContextValue = {
  id: string;
  describedBy?: string;
  invalid: boolean;
  required: boolean;
};

const FieldContext = createContext<FieldContextValue | null>(null);

function useFieldContext(): Partial<FieldContextValue> {
  return useContext(FieldContext) ?? {};
}

export type FieldProps = {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** Mensaje de éxito breve tras guardar (feedback inline). */
  success?: ReactNode;
  id?: string;
  className?: string;
  children: ReactNode;
};

/**
 * Campo de formulario: label siempre visible (nunca placeholder como label),
 * hint y error conectados por aria-describedby.
 */
export function Field({
  label,
  hint,
  error,
  success,
  required = false,
  id: idProp,
  className,
  children,
}: FieldProps) {
  const auto = useId();
  const id = idProp ?? auto;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  const invalid = Boolean(error);

  return (
    <FieldContext.Provider value={{ id, describedBy, invalid, required }}>
      <div className={cn("field", className)}>
        {label && (
          <span className="flex items-baseline gap-1">
            <label htmlFor={id}>{label}</label>
            {required && (
              <span className="text-danger" aria-hidden>
                *
              </span>
            )}
          </span>
        )}
        {children}
        {error ? (
          <p id={errorId} className="field-error" role="alert">
            {error}
          </p>
        ) : (
          success && (
            <p className="flex items-center gap-1.5 text-[13px] font-medium text-ok" role="status">
              <CheckCircle size={14} weight="fill" aria-hidden />
              {success}
            </p>
          )
        )}
        {hint && (
          <p id={hintId} className="field-hint">
            {hint}
          </p>
        )}
      </div>
    </FieldContext.Provider>
  );
}

/* ------------------------------------------------------------------ */
/* Inputs                                                              */
/* ------------------------------------------------------------------ */

export type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  icon?: Icon;
};

export function Input({ icon: IconEl, className, id, ...rest }: InputProps) {
  const ctx = useFieldContext();
  const input = (
    <input
      id={ctx.id ?? id}
      aria-describedby={ctx.describedBy}
      aria-invalid={ctx.invalid || undefined}
      aria-required={ctx.required || undefined}
      className={cn("input", IconEl && "pl-9", className)}
      {...rest}
    />
  );
  if (!IconEl) return input;
  return (
    <span className="relative block">
      <IconEl
        size={16}
        className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ghost"
        aria-hidden
      />
      {input}
    </span>
  );
}

export function Textarea({ className, id, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ctx = useFieldContext();
  return (
    <textarea
      id={ctx.id ?? id}
      aria-describedby={ctx.describedBy}
      aria-invalid={ctx.invalid || undefined}
      aria-required={ctx.required || undefined}
      className={cn("input min-h-20 resize-y leading-relaxed", className)}
      {...rest}
    />
  );
}

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  children: ReactNode;
  /** Permite una opción vacía con label propio. */
  placeholder?: string;
};

export function Select({ className, id, children, placeholder, ...rest }: SelectProps) {
  const ctx = useFieldContext();
  return (
    <select
      id={ctx.id ?? id}
      aria-describedby={ctx.describedBy}
      aria-invalid={ctx.invalid || undefined}
      aria-required={ctx.required || undefined}
      className={cn("input cursor-pointer pr-8", className)}
      {...rest}
    >
      {placeholder && <option value="">{placeholder}</option>}
      {children}
    </select>
  );
}

/**
 * Input de contraseña con toggle de visibilidad y aviso de Bloq Mayús.
 *
 * Respuesta en el pointer-down (`active:`) y transición CSS de los iconos: el
 * control se siente inmediato sin costo de render (este módulo lo importa casi
 * toda la app). El aviso de Bloq Mayús aparece con el estado real del teclado y
 * se va solo al desenfocar.
 */
export function PasswordInput({ className, id, onKeyDown, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  const [visible, setVisible] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const ctx = useFieldContext();
  const inputId = ctx.id ?? id;
  const capsId = `${inputId}-caps`;

  const describedBy =
    [ctx.describedBy, capsLock && !visible ? capsId : undefined].filter(Boolean).join(" ") ||
    undefined;

  function syncCapsLock(nativeEvent: Event) {
    const read = (nativeEvent as KeyboardEvent).getModifierState;
    if (typeof read !== "function") return;
    setCapsLock(read.call(nativeEvent, "CapsLock"));
  }

  const iconBase =
    "absolute inset-0 transition-[opacity,transform] duration-200 ease-[var(--ease-out)]";

  return (
    <span className="block">
      <span className="relative block">
        <input
          type={visible ? "text" : "password"}
          id={inputId}
          aria-describedby={describedBy}
          aria-invalid={ctx.invalid || undefined}
          aria-required={ctx.required || undefined}
          className={cn("input pr-10", className)}
          onKeyDown={(event) => {
            syncCapsLock(event.nativeEvent);
            onKeyDown?.(event);
          }}
          onKeyUp={(event) => syncCapsLock(event.nativeEvent)}
          onBlur={() => setCapsLock(false)}
          {...rest}
        />
        <button
          type="button"
          className="absolute top-1/2 right-1.5 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-xs text-ghost transition-[background-color,color,transform] duration-150 hover:bg-soft hover:text-text active:scale-90"
          title={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
          aria-pressed={visible}
          onClick={() => setVisible((v) => !v)}
        >
          <span className="relative inline-flex h-4 w-4 items-center justify-center">
            <Eye
              size={16}
              aria-hidden
              className={cn(
                iconBase,
                visible ? "scale-75 -rotate-12 opacity-0" : "scale-100 rotate-0 opacity-100"
              )}
            />
            <EyeSlash
              size={16}
              aria-hidden
              className={cn(
                iconBase,
                visible ? "scale-100 rotate-0 opacity-100" : "scale-75 rotate-12 opacity-0"
              )}
            />
          </span>
          <span className="sr-only">{visible ? "Ocultar contraseña" : "Mostrar contraseña"}</span>
        </button>
      </span>
      {capsLock && !visible && (
        <span
          id={capsId}
          role="status"
          className="animate-rise mt-1 flex items-center gap-1.5 text-xs font-medium text-warn"
        >
          <WarningCircle size={13} weight="fill" aria-hidden />
          Bloq Mayús está activado
        </span>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Checkbox y Switch                                                   */
/* ------------------------------------------------------------------ */

export type CheckboxProps = {
  checked: boolean | "indeterminate";
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
  id?: string;
} & Omit<ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>, "checked" | "onCheckedChange" | "id" | "className">;

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  className,
  id: idProp,
  ...rest
}: CheckboxProps) {
  const auto = useId();
  const id = idProp ?? auto;
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <CheckboxPrimitive.Root
        id={id}
        checked={checked}
        onCheckedChange={(v) => onCheckedChange(v === true)}
        disabled={disabled}
        aria-describedby={hintId}
        className="mt-px inline-flex h-[18px] w-[18px] shrink-0 cursor-pointer items-center justify-center rounded-xs border border-border-strong bg-control transition-colors duration-150 hover:border-faint data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=checked]:text-accent-fg data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent data-[state=indeterminate]:text-accent-fg disabled:cursor-not-allowed disabled:opacity-45"
        {...rest}
      >
        <CheckboxPrimitive.Indicator>
          {checked === "indeterminate" ? (
            <span className="block h-0.5 w-2.5 rounded-full bg-current" />
          ) : (
            <Check size={13} weight="bold" aria-hidden />
          )}
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      <label htmlFor={id} className={cn("text-[13px] leading-snug text-text", !disabled && "cursor-pointer")}>
        {label}
        {hint && (
          <span id={hintId} className="mt-0.5 block text-xs text-faint">
            {hint}
          </span>
        )}
      </label>
    </div>
  );
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  className,
  ...rest
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
} & Omit<ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>, "checked" | "onCheckedChange" | "disabled" | "className">) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <label htmlFor={id} className={cn("text-[13px] leading-snug text-text", !disabled && "cursor-pointer")}>
        {label}
        {hint && (
          <span id={hintId} className="mt-0.5 block text-xs text-faint">
            {hint}
          </span>
        )}
      </label>
      <SwitchPrimitive.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-describedby={hintId}
        className="relative h-[22px] w-[38px] shrink-0 cursor-pointer rounded-full border border-border bg-control transition-colors duration-200 data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:cursor-not-allowed disabled:opacity-45"
        {...rest}
      >
        <SwitchPrimitive.Thumb className="block h-4 w-4 translate-x-[3px] rounded-full bg-faint transition-transform duration-200 ease-[var(--ease-out)] data-[state=checked]:translate-x-[19px] data-[state=checked]:bg-accent-fg" />
      </SwitchPrimitive.Root>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Acciones y estado de guardado                                       */
/* ------------------------------------------------------------------ */

export function FormActions({
  children,
  sticky = false,
  className,
}: {
  children: ReactNode;
  sticky?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-end gap-2",
        sticky && "sticky bottom-0 z-10 -mx-4 border-t border-border bg-surface/95 px-4 py-3 backdrop-blur",
        className
      )}
    >
      {children}
    </div>
  );
}

export type SaveState = "idle" | "saving" | "saved" | "dirty" | "error";

/** Estado de persistencia visible: guardando / guardado / sin guardar / error. */
export function SaveStatus({
  state,
  error,
  savedLabel = "Guardado",
  dirtyLabel = "Sin guardar",
  className,
}: {
  state: SaveState;
  error?: string;
  savedLabel?: string;
  dirtyLabel?: string;
  className?: string;
}) {
  if (state === "idle") return null;
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs", className)}
      role="status"
      aria-live="polite"
    >
      {state === "saving" && (
        <>
          <CircleNotch size={13} className="animate-spin text-muted" aria-hidden />
          <span className="text-muted">Guardando…</span>
        </>
      )}
      {state === "saved" && (
        <>
          <CheckCircle size={13} weight="fill" className="text-ok" aria-hidden />
          <span className="text-ok">{savedLabel}</span>
        </>
      )}
      {state === "dirty" && <span className="text-warn">{dirtyLabel}</span>}
      {state === "error" && (
        <>
          <WarningCircle size={13} weight="fill" className="text-danger" aria-hidden />
          <span className="text-danger">{error || "No pudimos guardar"}</span>
        </>
      )}
    </span>
  );
}
