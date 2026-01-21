import { useEffect, useRef, useState } from "react";

export default function useAnimatedNumber(value, { duration = 420 } = {}) {
  const [current, setCurrent] = useState(value);
  const rafRef = useRef(null);
  const startRef = useRef(0);
  const fromRef = useRef(value);

  useEffect(() => {
    const start = performance.now();
    startRef.current = start;
    const from = fromRef.current;
    const to = Number(value);

    const step = (now) => {
      const elapsed = now - startRef.current;
      const t = Math.min(1, elapsed / duration);
      const eased = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
      const next = from + (to - from) * eased;
      setCurrent(next);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(step);
      }
    };

    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
    }
    rafRef.current = requestAnimationFrame(step);
    fromRef.current = to;

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [value, duration]);

  return current;
}
