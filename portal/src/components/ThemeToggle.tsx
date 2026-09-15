import { CaretUpDown, Check, Monitor, Moon, Sun } from "@phosphor-icons/react";
import { useTheme, type ThemePreference } from "../lib/theme";
import { Menu, MenuLabel, MenuRadioGroup, MenuRadioItem } from "./ui/overlay";
import { cn } from "./ui/cn";

const OPTIONS: { id: ThemePreference; label: string; icon: typeof Sun }[] = [
  { id: "system", label: "Sistema", icon: Monitor },
  { id: "light", label: "Claro", icon: Sun },
  { id: "dark", label: "Oscuro", icon: Moon },
];

/** Selector de tema en menú (no un switch sol/luna de dos estados). */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference, resolved } = useTheme();
  const current = OPTIONS.find((o) => o.id === preference) ?? OPTIONS[0];
  const CurrentIcon = resolved === "light" ? Sun : Moon;

  return (
    <Menu
      label="Tema de color"
      align="end"
      trigger={
        <button
          type="button"
          className={cn(
            "inline-flex cursor-pointer items-center gap-1.5 rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text",
            compact ? "h-9 w-9 justify-center" : "h-9 px-2"
          )}
          aria-label={`Tema: ${current.label}`}
          title={`Tema: ${current.label}`}
        >
          <CurrentIcon size={16} aria-hidden />
          {!compact && <span className="hidden text-xs sm:inline">{current.label}</span>}
          {!compact && <CaretUpDown size={11} className="text-ghost" aria-hidden />}
        </button>
      }
      className="min-w-[10rem]"
    >
      <MenuLabel>Tema</MenuLabel>
      <MenuRadioGroup value={preference} onValueChange={(v) => setPreference(v as ThemePreference)}>
        {OPTIONS.map((opt) => (
          <MenuRadioItem
            key={opt.id}
            value={opt.id}
            className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] text-muted outline-none select-none data-[highlighted]:bg-soft data-[highlighted]:text-text"
          >
            <opt.icon size={15} aria-hidden />
            <span className="flex-1">{opt.label}</span>
            {preference === opt.id && <Check size={13} weight="bold" className="text-accent" aria-hidden />}
          </MenuRadioItem>
        ))}
      </MenuRadioGroup>
    </Menu>
  );
}
