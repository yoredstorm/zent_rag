import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Une clases Tailwind resolviendo conflictos. Base de todas las primitivas. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
