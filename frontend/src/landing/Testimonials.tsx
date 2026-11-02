import { useState, type CSSProperties } from 'react';
import Reveal from './Reveal';

const TESTIMONIALS = [
  { initials: 'MK', name: 'Maya Kessler', role: 'Head of Engineering, Northlane',
    quote: 'Verixa completely changed how our team ships. Every pull request gets tested, investigated, and reported before we even open the diff.' },
  { initials: 'DA', name: 'Diego Alvarez', role: 'Staff Engineer, Fenwick Robotics',
    quote: 'It feels like we hired a QA engineer who never sleeps. Bugs get caught and ticketed before they ever reach staging.' },
  { initials: 'PN', name: 'Priya Nair', role: 'CTO, Loopline',
    quote: 'The investigation reports alone save us hours every week. We finally review pull requests with context instead of guessing.' },
];

// Plays like a short ad: the active pill fills up, then the next review takes over.
// There is no timer: the end of the fill animation moves on, so pausing the animation (hover, focus, off screen) pauses it.
export default function Testimonials() {
  const [active, setActive] = useState(0);
  const current = TESTIMONIALS[active];
  const next = () => setActive(i => (i + 1) % TESTIMONIALS.length);

  return (
    <section className="section" id="reviews">
      <Reveal className="section-head">
        <div className="eyebrow">Reviews</div>
        <h2>Teams ship with fewer surprises.</h2>
      </Reveal>

      <Reveal className="reviews">
        <div className="reviews-glow" style={{ '--slot': active } as CSSProperties} aria-hidden="true"></div>

        <figure className="review" key={active} aria-live="polite">
          <span className="review-mark" aria-hidden="true">“</span>
          <blockquote>
            {current.quote.split(' ').map((word, i) => (
              <span key={i} className="word" style={{ '--i': i } as CSSProperties}>{word} </span>
            ))}
          </blockquote>
          <figcaption>
            <span className="review-avatar">{current.initials}</span>
            <span><b>{current.name}</b><small>{current.role}</small></span>
          </figcaption>
        </figure>

        <div className="review-pills" role="group" aria-label="Choose a review">
          {TESTIMONIALS.map((t, i) => (
            <button key={t.name} type="button" className={'review-pill' + (i === active ? ' on' : '')}
                    aria-pressed={i === active} onClick={() => setActive(i)}>
              <span className="review-avatar sm">{t.initials}</span>
              <span>{t.name}</span>
              {i === active && <i className="review-fill" key={active} onAnimationEnd={next}></i>}
            </button>
          ))}
        </div>
      </Reveal>
    </section>
  );
}
