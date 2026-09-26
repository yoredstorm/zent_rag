import { CircleNotch, type Icon } from "@phosphor-icons/react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../ui/cn";

/**
 * CTA de las pantallas de acceso: píldora con el icono anidado en su propio
 * círculo (botón dentro del botón). El círculo se desplaza en diagonal al pasar
 * el puntero, y el botón entero se hunde al presionar: tensión cinética interna
 * en lugar de un cambio de color.
 */
export function AuthButton({
  children,
  icon: IconEl,
  loading = false,
  className,
  disabled,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: Icon; loading?: boolean }) {
  return (
    <button
      type={type}
      className={cn("auth-cta group", className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      <span className="auth-cta__label">{children}</span>
      <span className="auth-cta__badge" aria-hidden>
        {loading ? (
          <CircleNotch size={15} weight="light" className="animate-spin" />
        ) : (
          IconEl && <IconEl size={15} weight="light" />
        )}
      </span>
    </button>
  );
}
