import type { Icon } from "@phosphor-icons/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { cn } from "./cn";
import { Spinner } from "./states";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "md" | "sm";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  danger: "btn-danger",
  ghost: "btn-ghost",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  md: "",
  sm: "btn-sm",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leadingIcon?: Icon;
  trailingIcon?: Icon;
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  leadingIcon: Leading,
  trailingIcon: Trailing,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn("btn", VARIANT_CLASS[variant], SIZE_CLASS[size], className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <Spinner size={size === "sm" ? 13 : 15} />
      ) : (
        Leading && <Leading size={size === "sm" ? 14 : 16} weight="regular" aria-hidden />
      )}
      {children}
      {Trailing && !loading && (
        <Trailing size={size === "sm" ? 14 : 16} weight="regular" aria-hidden />
      )}
    </button>
  );
}

export type ButtonLinkProps = Omit<LinkProps, "className"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  leadingIcon?: Icon;
  trailingIcon?: Icon;
  className?: string;
  children?: ReactNode;
};

/** Variante navegable de Button. Mantiene el mismo lenguaje visual. */
export function ButtonLink({
  variant = "secondary",
  size = "md",
  leadingIcon: Leading,
  trailingIcon: Trailing,
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link
      className={cn("btn no-underline", VARIANT_CLASS[variant], SIZE_CLASS[size], className)}
      {...rest}
    >
      {Leading && <Leading size={size === "sm" ? 14 : 16} weight="regular" aria-hidden />}
      {children}
      {Trailing && <Trailing size={size === "sm" ? 14 : 16} weight="regular" aria-hidden />}
    </Link>
  );
}

export type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> & {
  /** Obligatorio: es el nombre accesible del control. */
  label: string;
  icon: Icon;
  variant?: Extract<ButtonVariant, "ghost" | "secondary" | "primary" | "danger">;
  iconSize?: number;
  loading?: boolean;
};

export function IconButton({
  label,
  icon: IconEl,
  variant = "ghost",
  iconSize = 17,
  loading = false,
  className,
  disabled,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "btn btn-icon shrink-0",
        VARIANT_CLASS[variant],
        className
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <Spinner size={iconSize - 2} />
      ) : (
        <IconEl size={iconSize} weight="regular" aria-hidden />
      )}
    </button>
  );
}
