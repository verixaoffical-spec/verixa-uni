import { useEffect, useState } from 'react';
import { loader } from '../shared/loader';
import Reveal, { RevealReady } from './Reveal';
import Navbar from './Navbar';
import Hero from './Hero';
import IntroVideo from './IntroVideo';
import Features from './Features';
import Testimonials from './Testimonials';
import Footer from './Footer';

export default function Landing() {
  const [ready, setReady] = useState(false);

  // Lift the loader once the page (images and fonts) has loaded, or after 6 seconds at most.
  useEffect(() => {
    const pageLoaded = new Promise<void>(resolve => {
      if (document.readyState === 'complete') resolve();
      else addEventListener('load', () => resolve(), { once: true });
    });
    const timeout = new Promise<void>(resolve => setTimeout(resolve, 6000));
    Promise.race([pageLoaded, timeout]).then(() => loader.hide()).then(() => setReady(true));
  }, []);

  return (
    <RevealReady.Provider value={ready}>
      {/* Outside every section, so it stays at the top for the whole page */}
      <Navbar />
      <Hero />
      <section className="section tour" id="video">
        <Reveal className="section-head">
          <div className="eyebrow">Product tour</div>
          <h2>See Verixa in action.</h2>
          <p>Sign up, connect GitHub and Jira, upload your tests, and secure your account, recorded from the real product.</p>
        </Reveal>
        <Reveal delay={1}><IntroVideo /></Reveal>
      </section>
      <Features />
      <Testimonials />
      <Footer />
    </RevealReady.Provider>
  );
}
