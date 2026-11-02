import { useEffect, useRef } from 'react';
import Reveal from './Reveal';
import MockDashboard from './MockDashboard';
import { clamp, hoverCapable, lerp, reduceMotion } from './motion';

export default function Hero() {
  const heroRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // The product picture starts leaned back, straightens as you scroll, and tilts toward the pointer.
  // This runs on every scroll frame, so it sets styles directly instead of through React state.
  useEffect(() => {
    const hero = heroRef.current!, content = contentRef.current!, wrap = wrapRef.current!, panel = panelRef.current!;
    let rotateX = 30, scale = 0.9, z = -180;  // from scrolling
    let tiltX = 0, tiltY = 0;                 // from the pointer

    function paint() {
      panel.style.transform = `translateZ(${z}px) rotateX(${rotateX + tiltX}deg) rotateY(${tiltY}deg) scale(${scale})`;
      const depth = Math.abs(tiltX) + Math.abs(tiltY);
      panel.style.boxShadow = `0 ${50 + depth * 3}px ${140 + depth * 4}px -30px hsl(var(--accent) / ${0.45 + depth * 0.01}), 0 0 0 1px rgba(255,255,255,0.04)`;
    }

    function onScroll() {
      const progress = clamp(-hero.getBoundingClientRect().top / hero.offsetHeight, 0, 1);
      const textProgress = clamp(progress / 0.5, 0, 1);
      content.style.transform = `translateY(${textProgress * -160}px)`;
      content.style.opacity = String(1 - textProgress);
      wrap.style.transform = `translateY(${progress * -180}px)`;

      const tilt = clamp((progress - 0.05) / 0.55, 0, 1);   // straightening up
      const past = clamp((progress - 0.62) / 0.38, 0, 1);   // scrolling past it
      rotateX = lerp(30, -5, tilt) - past * 9;
      scale = lerp(0.9, 1, clamp(tilt * 1.3, 0, 1)) - past * 0.03;
      z = lerp(-180, 0, tilt) + past * 50;
      paint();
    }

    function onMouseMove(e: MouseEvent) {
      const rect = panel.getBoundingClientRect();
      tiltY = (clamp((e.clientX - rect.left) / rect.width, 0, 1) - 0.5) * 10;
      tiltX = (0.5 - clamp((e.clientY - rect.top) / rect.height, 0, 1)) * 6;
      paint();
    }

    function onMouseLeave() {
      tiltX = 0; tiltY = 0;
      paint();
    }

    onScroll();
    addEventListener('scroll', onScroll, { passive: true });
    const followPointer = hoverCapable && !reduceMotion;
    if (followPointer) {
      wrap.addEventListener('mousemove', onMouseMove);
      wrap.addEventListener('mouseleave', onMouseLeave);
    }
    return () => {
      removeEventListener('scroll', onScroll);
      wrap.removeEventListener('mousemove', onMouseMove);
      wrap.removeEventListener('mouseleave', onMouseLeave);
    };
  }, []);

  return (
    <section className="hero" id="top" ref={heroRef}>
      <div className="hero-content" ref={contentRef}>
        <Reveal delay={0}>
          <a className="tag-pill" href="#video">
            <span className="tag-badge">New</span>Say hello to Verixa Agents v1.0
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
          </a>
        </Reveal>

        <Reveal as="h1" delay={1} className="hero-title">
          Your pull requests.<br />One clear <em>verdict</em>.
        </Reveal>

        <Reveal as="p" delay={2} className="hero-sub">
          Verixa tests, investigates, and files tickets for every pull request, automatically.
        </Reveal>

        <Reveal delay={3} className="hero-ctas">
          <a className="btn solid lg" href="/signup">Get started for free</a>
          <a className="btn ghost lg" href="#video">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l13-7.5z" /></svg>Watch the product tour
          </a>
        </Reveal>
      </div>

      <Reveal delay={4}>
        <div className="dash-wrap" ref={wrapRef}>
          <div className="dash-bg"></div>
          <div className="dash-panel" ref={panelRef}><MockDashboard /></div>
          <div className="dash-fade"></div>
        </div>
      </Reveal>
    </section>
  );
}
