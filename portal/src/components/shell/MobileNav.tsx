import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "@phosphor-icons/react";
import { AppSidebar } from "./AppSidebar";
import { IconButton } from "../ui/Button";

/** Navegación móvil: drawer lateral con el mismo sidebar, sin duplicar lógica. */
export function MobileNav({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[var(--z-drawer)] animate-fade-in bg-scrim data-[state=closed]:animate-fade-out lg:hidden" />
        <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-[var(--z-drawer)] flex w-[290px] max-w-[86vw] flex-col animate-slide-in-left border-r border-border bg-surface shadow-pop outline-none data-[state=closed]:animate-slide-out-left lg:hidden">
          <DialogPrimitive.Title className="sr-only">Menú de navegación</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Navegación principal del workspace.
          </DialogPrimitive.Description>
          <div className="absolute top-3.5 right-3 z-10">
            <DialogPrimitive.Close asChild>
              <IconButton label="Cerrar menú" icon={X} className="h-9 w-9 min-h-0" />
            </DialogPrimitive.Close>
          </div>
          <AppSidebar
            collapsed={false}
            instanceId="mobile"
            showCollapseToggle={false}
            onNavigate={() => onOpenChange(false)}
          />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
