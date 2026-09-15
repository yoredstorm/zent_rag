import * as TabsPrimitive from "@radix-ui/react-tabs";
import { motion, useReducedMotion } from "motion/react";
import { createContext, useContext, useId, useState, type ReactNode } from "react";
import type { Icon } from "@phosphor-icons/react";
import { cn } from "./cn";

type TabVariant = "underline" | "pill";

const TabsContext = createContext<{ uid: string; variant: TabVariant; current?: string }>({
  uid: "tabs",
  variant: "underline",
});

export type TabsProps = {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  variant?: TabVariant;
  children: ReactNode;
  className?: string;
};

/**
 * Tabs con indicador animado (layout transition real, no un borde que salta).
 * `pill` para controles segmentados, `underline` para navegación de sección.
 */
export function Tabs({
  value,
  defaultValue,
  onValueChange,
  variant = "underline",
  children,
  className,
}: TabsProps) {
  const uid = useId();
  const [internal, setInternal] = useState(defaultValue);
  const current = value ?? internal;

  return (
    <TabsContext.Provider value={{ uid, variant, current }}>
      <TabsPrimitive.Root
        {...(value !== undefined ? { value } : { defaultValue })}
        onValueChange={(next) => {
          setInternal(next);
          onValueChange?.(next);
        }}
        className={className}
      >
        {children}
      </TabsPrimitive.Root>
    </TabsContext.Provider>
  );
}

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  const { variant } = useContext(TabsContext);
  return (
    <TabsPrimitive.List
      className={cn(
        variant === "underline"
          ? "flex flex-wrap items-center gap-1 border-b border-border"
          : "inline-flex items-center gap-0.5 rounded-md border border-border bg-soft p-0.5",
        className
      )}
    >
      {children}
    </TabsPrimitive.List>
  );
}

export type TabsTriggerProps = {
  value: string;
  children: ReactNode;
  icon?: Icon;
  disabled?: boolean;
  className?: string;
};

export function TabsTrigger({
  value,
  children,
  icon: IconEl,
  disabled,
  className,
}: TabsTriggerProps) {
  const { uid, variant, current } = useContext(TabsContext);
  const active = current === value;
  const reduce = useReducedMotion();

  const layoutTransition = reduce
    ? { duration: 0 }
    : { type: "spring" as const, stiffness: 520, damping: 42, mass: 0.6 };

  return (
    <TabsPrimitive.Trigger
      value={value}
      disabled={disabled}
      className={cn(
        "relative inline-flex cursor-pointer items-center gap-1.5 font-medium whitespace-nowrap transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-45",
        variant === "underline"
          ? "-mb-px min-h-10 rounded-t-sm px-3 text-[13.5px]"
          : "min-h-8 rounded-sm px-3 text-[13px]",
        active ? "text-text" : "text-muted hover:text-text",
        className
      )}
    >
      {active && variant === "underline" && (
        <motion.span
          layoutId={`${uid}-underline`}
          className="absolute inset-x-1 -bottom-px h-[2px] rounded-full bg-accent"
          transition={layoutTransition}
          aria-hidden
        />
      )}
      {active && variant === "pill" && (
        <motion.span
          layoutId={`${uid}-pill`}
          className="absolute inset-0 rounded-sm bg-surface shadow-panel"
          transition={layoutTransition}
          aria-hidden
        />
      )}
      <span className="relative z-10 inline-flex items-center gap-1.5">
        {IconEl && <IconEl size={15} weight={active ? "fill" : "regular"} aria-hidden />}
        {children}
      </span>
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <TabsPrimitive.Content value={value} className={cn("mt-4 outline-none", className)}>
      {children}
    </TabsPrimitive.Content>
  );
}
