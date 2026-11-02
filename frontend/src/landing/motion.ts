import type { MouseEvent } from 'react';

export const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
export const hoverCapable = matchMedia('(hover:hover) and (pointer:fine)').matches;

export const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

// "Magnetic" hover: the element leans a little toward the pointer. Spread these onto any element.
export const magnetic = hoverCapable && !reduceMotion
  ? {
      onMouseMove(e: MouseEvent<HTMLElement>) {
        const el = e.currentTarget, rect = el.getBoundingClientRect();
        const x = e.clientX - rect.left - rect.width / 2;
        const y = e.clientY - rect.top - rect.height / 2;
        el.style.transform = `translate(${x * 0.25}px, ${y * 0.35}px)`;
      },
      onMouseLeave(e: MouseEvent<HTMLElement>) {
        e.currentTarget.style.transform = '';
      },
    }
  : {};
