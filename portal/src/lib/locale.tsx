import { createContext, useContext, type ReactNode } from "react";

/**
 * Configuración de localización centralizada (FASE 14).
 * Por ahora un solo idioma predominante (español) con formato canónico.
 * Cuando exista i18n real, este contexto pasa a ser la fuente de `t()`.
 */

export const LOCALE = "es-PE";
export const LANGUAGE = "es";
export const TIMEZONE = "America/Lima";
export const CURRENCY = "USD";

export type LocaleConfig = {
  locale: string;
  language: string;
  timezone: string;
  currency: string;
};

const LocaleContext = createContext<LocaleConfig>({
  locale: LOCALE,
  language: LANGUAGE,
  timezone: TIMEZONE,
  currency: CURRENCY,
});

export function LocaleProvider({ children }: { children: ReactNode }) {
  return (
    <LocaleContext.Provider
      value={{ locale: LOCALE, language: LANGUAGE, timezone: TIMEZONE, currency: CURRENCY }}
    >
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale(): LocaleConfig {
  return useContext(LocaleContext);
}