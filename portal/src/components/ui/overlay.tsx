import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { Button, IconButton } from "./Button";
import { Field, Input } from "./form";
import { useEffect, useState, type HTMLAttributes } from "react";

/* ------------------------------------------------------------------ */
/* Tooltip                                                             */
/* ------------------------------------------------------------------ */

export type TooltipProps = {
  label: ReactNode;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  delay?: number;
};

/** Tooltip breve. No usar para contenido interactivo: para eso, Popover. */
export function Tooltip({ label, children, side = "top", align = "center", delay = 320 }: TooltipProps) {
  return (
    <TooltipPrimitive.Provider delayDuration={delay} skipDelayDuration={200}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            align={align}
            sideOffset={6}
            collisionPadding={8}
            className="z-[var(--z-palette)] max-w-[min(20rem,calc(100vw-2rem))] animate-pop-in rounded-sm border border-border bg-overlay px-2.5 py-1.5 text-[12.5px] leading-snug text-text shadow-pop"
            style={{ transformOrigin: "var(--radix-tooltip-content-transform-origin)" }}
          >
            {label}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

/* ------------------------------------------------------------------ */
/* Popover                                                             */
/* ------------------------------------------------------------------ */

export type PopoverProps = {
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  sideOffset?: number;
  className?: string;
  /** Ancho mínimo del panel. */
  width?: number | string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  modal?: boolean;
};

export function Popover({
  trigger,
  children,
  align = "end",
  side = "bottom",
  sideOffset = 6,
  className,
  width,
  open,
  onOpenChange,
  modal = false,
}: PopoverProps) {
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange} modal={modal}>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align={align}
          side={side}
          sideOffset={sideOffset}
          collisionPadding={10}
          className={cn(
            "z-[var(--z-modal)] animate-pop-in rounded-lg border border-border bg-overlay p-3 shadow-pop",
            className
          )}
          style={{
            transformOrigin: "var(--radix-popover-content-transform-origin)",
            width,
          }}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

/* ------------------------------------------------------------------ */
/* Menú desplegable                                                    */
/* ------------------------------------------------------------------ */

export type MenuProps = {
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
  /** Etiqueta accesible del menú. */
  label?: string;
};

export function Menu({ trigger, children, align = "end", side = "bottom", className, label }: MenuProps) {
  return (
    <DropdownPrimitive.Root>
      <DropdownPrimitive.Trigger asChild>{trigger}</DropdownPrimitive.Trigger>
      <DropdownPrimitive.Portal>
        <DropdownPrimitive.Content
          align={align}
          side={side}
          sideOffset={6}
          collisionPadding={8}
          aria-label={label}
          className={cn(
            "z-[var(--z-modal)] min-w-[11rem] animate-pop-in overflow-hidden rounded-lg border border-border bg-overlay p-1 shadow-pop",
            className
          )}
          style={{ transformOrigin: "var(--radix-dropdown-menu-content-transform-origin)" }}
        >
          {children}
        </DropdownPrimitive.Content>
      </DropdownPrimitive.Portal>
    </DropdownPrimitive.Root>
  );
}

export const MenuItem = DropdownPrimitive.Item;
export const MenuSeparator = DropdownPrimitive.Separator;
export const MenuLabel = DropdownPrimitive.Label;
export const MenuCheckboxItem = DropdownPrimitive.CheckboxItem;
export const MenuRadioGroup = DropdownPrimitive.RadioGroup;
export const MenuRadioItem = DropdownPrimitive.RadioItem;
export const MenuSub = DropdownPrimitive.Sub;
export const MenuSubTrigger = DropdownPrimitive.SubTrigger;
export const MenuSubContent = DropdownPrimitive.SubContent;

/** Estilos base compartidos por los ítems de menú (Radix aplica data-highlighted). */
export const menuItemClass =
  "flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] text-muted outline-none select-none data-[highlighted]:bg-soft data-[highlighted]:text-text data-[disabled]:pointer-events-none data-[disabled]:opacity-45";

export const menuLabelClass =
  "px-2.5 py-1.5 text-[11px] font-semibold tracking-[0.07em] text-faint uppercase";

export const menuSeparatorClass = "my-1 h-px bg-border";

/* ------------------------------------------------------------------ */
/* Modal                                                               */
/* ------------------------------------------------------------------ */

export type ModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** Oculta el botón de cierre (para flujos que exigen decisión). */
  hideClose?: boolean;
  closeLabel?: string;
  /** `alertdialog` para confirmaciones que exigen atención inmediata. */
  role?: "dialog" | "alertdialog";
  className?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, "children">;

const MODAL_SIZE: Record<NonNullable<ModalProps["size"]>, string> = {
  sm: "max-w-[400px]",
  md: "max-w-[520px]",
  lg: "max-w-[720px]",
};

/** Diálogo centrado. Para inspección contextual usar Drawer. */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
  hideClose = false,
  closeLabel = "Cerrar",
  role = "dialog",
  className,
  ...rest
}: ModalProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[var(--z-modal)] animate-fade-in bg-scrim backdrop-blur-[2px] data-[state=closed]:animate-fade-out" />
        <DialogPrimitive.Content
          role={role}
          className={cn(
            "fixed top-1/2 left-1/2 z-[var(--z-modal)] flex max-h-[min(88dvh,900px)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col animate-pop-in rounded-xl border border-border bg-overlay shadow-pop data-[state=closed]:animate-pop-out",
            MODAL_SIZE[size],
            className
          )}
          {...rest}
        >
          <div className="flex items-start justify-between gap-4 px-5 pt-5 pb-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-h2">{title}</DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-1 text-[13px] leading-relaxed text-muted">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            {!hideClose && (
              <DialogPrimitive.Close asChild>
                <IconButton label={closeLabel} icon={X} className="-mt-1 -mr-1" />
              </DialogPrimitive.Close>
            )}
          </div>
          {children && <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5">{children}</div>}
          {footer && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3.5">
              {footer}
            </div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ------------------------------------------------------------------ */
/* Drawer                                                              */
/* ------------------------------------------------------------------ */

export type DrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  side?: "right" | "left" | "bottom";
  /** Ancho en px para side right/left. */
  width?: number;
  className?: string;
  /** Clases del scrim (permite ocultarlo por breakpoint cuando el panel es solo móvil). */
  overlayClassName?: string;
  closeLabel?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, "children">;

const DRAWER_SIDE: Record<NonNullable<DrawerProps["side"]>, string> = {
  right:
    "inset-y-0 right-0 h-full w-full border-l animate-slide-in-right data-[state=closed]:animate-slide-out-right",
  left: "inset-y-0 left-0 h-full w-full border-r animate-slide-in-left data-[state=closed]:animate-slide-out-left",
  bottom:
    "inset-x-0 bottom-0 max-h-[88dvh] border-t rounded-t-xl animate-slide-in-bottom data-[state=closed]:animate-slide-out-bottom",
};

/**
 * Panel lateral para inspección contextual: conserva el contexto principal
 * en pantalla mientras se ve el detalle.
 */
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  side = "right",
  width = 440,
  className,
  overlayClassName,
  closeLabel = "Cerrar panel",
  ...rest
}: DrawerProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-[var(--z-drawer)] animate-fade-in bg-scrim data-[state=closed]:animate-fade-out",
            overlayClassName
          )}
        />
        <DialogPrimitive.Content
          className={cn(
            "fixed z-[var(--z-drawer)] flex flex-col border-border bg-overlay shadow-pop outline-none",
            DRAWER_SIDE[side],
            className
          )}
          style={side === "bottom" ? undefined : { maxWidth: width }}
          {...rest}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-h3">{title}</DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-0.5 text-xs leading-relaxed text-muted">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close asChild>
              <IconButton label={closeLabel} icon={X} className="-mt-1 -mr-1" />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3.5">
              {footer}
            </div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ------------------------------------------------------------------ */
/* Confirmación                                                        */
/* ------------------------------------------------------------------ */

export type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  loading?: boolean;
  /**
   * Si se define, la persona debe escribir exactamente este texto para
   * habilitar la confirmación (revocar, rotar, restaurar, borrar en duro).
   */
  requireText?: string;
  requireTextLabel?: string;
  onConfirm: () => void;
};

/** Confirmación destructiva o irreversible, con confirmación escrita opcional. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  tone = "danger",
  loading = false,
  requireText,
  requireTextLabel,
  onConfirm,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const matches = !requireText || typed.trim() === requireText;

  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={body}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={loading}
            disabled={!matches}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {requireText && (
        <Field
          label={requireTextLabel ?? `Escribí «${requireText}» para confirmar`}
          hint="Esta acción no se puede deshacer."
        >
          <Input
            autoFocus
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={requireText}
            autoComplete="off"
          />
        </Field>
      )}
    </Modal>
  );
}
