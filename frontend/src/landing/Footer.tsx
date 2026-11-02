import { magnetic } from './motion';

const MARQUEE = ['Automated PR Testing', 'Instant Bug Investigation', 'Auto-Drafted Tickets', 'GitHub and Jira Sync', 'Two-Step Verification', 'Agents That Never Sleep'];

// The closing curtain: it is revealed from behind the page as you reach the end.
export default function Footer() {
  return (
    <footer className="curtain" id="contact">
      <div className="curtain-inner">
        <div className="curtain-aurora" aria-hidden="true"></div>
        <div className="curtain-grid" aria-hidden="true"></div>
        <div className="curtain-giant" aria-hidden="true">VERIXA</div>

        <div className="curtain-marquee" aria-hidden="true">
          {/* The list appears twice so the strip loops without a gap */}
          <div className="curtain-track">
            {[...MARQUEE, ...MARQUEE].map((text, i) => <span key={i}>{text}<b>✦</b></span>)}
          </div>
        </div>

        <div className="curtain-main">
          <h2>Ready to ship<br />with <em>confidence</em>?</h2>
          <div className="curtain-row">
            <a href="/signup" className="curtain-pill primary" {...magnetic}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l3 7h7l-5.5 4.5L18 21l-6-4-6 4 1.5-7.5L2 9h7z" /></svg>
              Get started for free
            </a>
            <a href="/#video" className="curtain-pill" {...magnetic}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l13-7.5z" /></svg>
              Watch the tour
            </a>
          </div>
          <nav className="curtain-row small" aria-label="Footer">
            <a href="/login" className="curtain-pill quiet" {...magnetic}>Log in</a>
            <a href="#" className="curtain-pill quiet" {...magnetic}>Privacy Policy</a>
            <a href="#" className="curtain-pill quiet" {...magnetic}>Terms of Service</a>
            <a href="#" className="curtain-pill quiet" {...magnetic}>Support</a>
          </nav>
        </div>

        <div className="curtain-bottom">
          <span>© 2026 Verixa. All rights reserved.</span>
          <span className="curtain-pill quiet static">Built for engineering teams</span>
          <a className="curtain-top" href="#top" aria-label="Back to top" {...magnetic}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10l7-7m0 0l7 7m-7-7v18" /></svg>
          </a>
        </div>
      </div>
    </footer>
  );
}
