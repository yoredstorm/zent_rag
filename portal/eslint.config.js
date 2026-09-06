import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "playwright-report", "test-results", "coverage"] },
  {
    files: ["public/**/*.js"],
    languageOptions: {
      globals: {
        window: "readonly",
        document: "readonly",
        localStorage: "readonly",
      },
    },
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: {
        window: "readonly",
        document: "readonly",
        navigator: "readonly",
        localStorage: "readonly",
        sessionStorage: "readonly",
        fetch: "readonly",
        crypto: "readonly",
        console: "readonly",
        URL: "readonly",
        RequestInit: "readonly",
        Headers: "readonly",
        AbortController: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        TextDecoder: "readonly",
        FileReader: "readonly",
        File: "readonly",
        FormData: "readonly",
        Blob: "readonly",
        performance: "readonly",
        matchMedia: "readonly",
        EventSource: "readonly",
        ReadableStream: "readonly",
        MediaQueryList: "readonly",
        MediaQueryListEvent: "readonly",
        HTMLDialogElement: "readonly",
        ResizeObserver: "readonly",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // El patrón fetch→setState en useEffect es el estilo de carga de datos
      // del portal; la regla v7 lo considera anti-patrón y no aplica aquí.
      "react-hooks/set-state-in-effect": "off",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  }
);