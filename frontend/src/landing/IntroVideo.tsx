import { useRef, useState, type CSSProperties, type ReactNode } from 'react';

// Where each part of the recording starts, in seconds. The video was recorded from the real Verixa interface;
// the GitHub and Atlassian approval screens in Connect (19.3s to 27.7s) are a mock-up.
const CHAPTERS: { label: string; at: number; icon: ReactNode }[] = [
  { label: 'Intro', at: 0, icon: <path d="M7 4.5v15l13-7.5z" /> },
  { label: 'Sign up', at: 7.8, icon: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" /></> },
  { label: 'Connect', at: 17.2, icon: <><path d="M12 22v-5" /><path d="M9 8V2M15 8V2" /><path d="M18 8v5a4 4 0 01-4 4h-4a4 4 0 01-4-4V8z" /></> },
  { label: 'Upload', at: 35.5, icon: <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6" /></> },
  { label: 'Secure', at: 47.5, icon: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /> },
  { label: 'Log in', at: 62.6, icon: <><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 018 0v4" /></> },
  { label: 'Up next', at: 76.7, icon: <path d="M3 17l6-6 4 4 8-8M15 7h6v6" /> },
];
const LENGTH = 85.6;

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

// The product video in a frame, with chapter buttons underneath that jump to each part.
export default function IntroVideo() {
  const video = useRef<HTMLVideoElement>(null);
  const [started, setStarted] = useState(false);
  const [time, setTime] = useState(0);

  function play(at?: number) {
    const v = video.current!;
    if (at !== undefined) v.currentTime = at;
    setStarted(true);
    v.play().catch(() => {});  // a browser may refuse; the controls are shown, so the person can press play
  }

  const active = CHAPTERS.reduce((found, c, i) => (time >= c.at - 0.05 ? i : found), 0);
  const progress = (i: number) => {
    const end = CHAPTERS[i + 1]?.at ?? LENGTH;
    return Math.min(1, Math.max(0, (time - CHAPTERS[i].at) / (end - CHAPTERS[i].at)));
  };

  return (
    <div className="video-frame">
      <div className="video-box">
        <video ref={video} src="/assets/video/verixa-intro.mp4" poster="/assets/video/verixa-intro-poster.jpg"
               preload="metadata" playsInline controls={started} aria-label="Intro to Verixa, an 86 second tour of the product"
               onTimeUpdate={e => setTime(e.currentTarget.currentTime)} />
        {!started && (
          <button className="video-cover" type="button" onClick={() => play()} aria-label="Play the intro to Verixa, 1 minute 26 seconds">
            <span className="video-play">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l13-7.5z" /></svg>Play
            </span>
            <span className="video-title">Intro to <em>Verixa</em></span>
            <span className="video-length">{clock(LENGTH)}</span>
          </button>
        )}
      </div>

      <div className="chapters" role="group" aria-label="Jump to a part of the video">
        {CHAPTERS.map((c, i) => {
          const on = started && i === active;
          return (
            <button key={c.label} type="button" className={'chapter' + (on ? ' on' : '')} aria-pressed={on}
                    style={{ '--p': on ? progress(i) : 0 } as CSSProperties} onClick={() => play(c.at)}>
              <svg viewBox="0 0 24 24" aria-hidden="true">{c.icon}</svg>
              <span>{c.label}</span>
              <small>{clock(c.at)}</small>
            </button>
          );
        })}
      </div>
    </div>
  );
}
