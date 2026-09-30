import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import { diveEffectOn, setDiveEffect, subscribeDiveEffect } from "./divePref";

/** Estado vivo del zoom de entrada: persiste y se comparte entre shell y páginas. */
export function useDiveEffect() {
  const reduce = useReducedMotion();
  const [on, setOn] = useState(diveEffectOn);
  useEffect(() => subscribeDiveEffect(setOn), []);
  const quiet = Boolean(reduce) || !on;
  return {
    on,
    quiet,
    set: setDiveEffect,
    toggle: () => setDiveEffect(!on),
  };
}
