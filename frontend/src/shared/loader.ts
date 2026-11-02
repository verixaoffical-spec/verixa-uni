// Controls the start loader that the page's HTML shows before React starts.
// Pages call loader.hide() once they are ready, and loader.show() before leaving.

const el = document.getElementById('pre-load');
const caption = el?.querySelector('.loader-caption small');
const bar = el?.querySelector<HTMLElement>('.loader-bar i');
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Each page says how long the loader stays at least: data-first on the first visit, data-repeat after that.
// A loader never makes anything faster, so only the landing page asks for a real pause.
function minimumTime(): number {
  if (!el || reduced) return 0;
  let firstVisit = true;
  try {
    const key = 'vx-seen:' + location.pathname;
    firstVisit = !sessionStorage.getItem(key);
    sessionStorage.setItem(key, '1');
  } catch {
    // Storage can be blocked. Treat it as a first visit.
  }
  const wanted = Number(firstVisit ? el.dataset.first : el.dataset.repeat);
  return Number.isFinite(wanted) ? wanted : 500;
}

const minimum = minimumTime();
const started = performance.now();
let hiding: Promise<void> | null = null;
let generation = 0;

if (el) {
  el.style.setProperty('--vx-min', minimum + 'ms');
  el.classList.add('on');
  document.documentElement.classList.add('is-loading');
}

export const loader = {
  hide(): Promise<void> {
    if (!el) return Promise.resolve();
    if (hiding) return hiding;
    const wait = Math.max(0, minimum - (performance.now() - started));
    const mine = generation;
    hiding = new Promise(resolve => setTimeout(() => {
      if (mine !== generation) return resolve();  // show() was called meanwhile, so stay visible
      el.classList.add('done');
      el.setAttribute('aria-hidden', 'true');
      document.documentElement.classList.remove('is-loading');
      setTimeout(resolve, reduced ? 0 : 300);  // resolve mid-fade, so the page's entrance overlaps the exit
    }, wait));
    return hiding;
  },

  show(text = '') {
    if (!el) return;
    hiding = null;
    generation++;
    if (caption) caption.textContent = text;
    el.removeAttribute('aria-hidden');
    el.classList.remove('done');
    if (bar) {  // refill the bar from zero
      bar.style.animation = 'none';
      void bar.offsetWidth;
      bar.style.animation = '';
    }
    document.documentElement.classList.add('is-loading');
  },
};
