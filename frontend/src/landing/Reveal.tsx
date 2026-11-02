import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';

// True once the start loader has lifted. Nothing fades in before that, so the entrance is never hidden behind it.
export const RevealReady = createContext(false);

interface Props {
  as?: 'div' | 'h1' | 'p';
  delay?: 0 | 1 | 2 | 3 | 4;  // matches the .reveal[data-d] rules in landing.css
  className?: string;
  id?: string;
  children: ReactNode;
}

// Fades its content in the first time it scrolls into view.
export default function Reveal({ as: Tag = 'div', delay = 0, className = '', id, children }: Props) {
  const ready = useContext(RevealReady);
  const ref = useRef<HTMLElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!ready || !ref.current) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShown(true);
        observer.disconnect();
      }
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [ready]);

  return (
    <Tag ref={ref as never} id={id} className={`${className} reveal${shown ? ' show' : ''}`} data-d={delay}>
      {children}
    </Tag>
  );
}
