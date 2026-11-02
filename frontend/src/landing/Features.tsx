import Reveal from './Reveal';

const FEATURES = [
  {
    title: 'Automated PR testing',
    text: 'Every pull request triggers a full test pass automatically. No pipelines to babysit, no waiting on CI.',
    icon: <><path d="M9 3v5.586a1 1 0 01-.293.707l-4.414 4.414A2 2 0 003 15.121V19a2 2 0 002 2h14a2 2 0 002-2v-3.879a2 2 0 00-1.293-1.414L15.293 9.293A1 1 0 0115 8.586V3" /><path d="M8 3h8M6 15h12" /></>,
  },
  {
    title: 'Root-cause investigation',
    text: 'When something breaks, Verixa traces it back through the diff and tells you exactly why, not just that it failed.',
    icon: <><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" /></>,
  },
  {
    title: 'Auto-drafted tickets',
    text: 'Bugs get filed in Jira with repro steps and context attached, ready for triage instead of another thing on your plate.',
    icon: <><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" /></>,
  },
  {
    title: 'GitHub and Jira in one step',
    text: 'One approval links both. Verixa picks the repository, the Jira project, and creates the webhook for you.',
    icon: <><path d="M12 22v-5" /><path d="M9 8V2M15 8V2" /><path d="M18 8v5a4 4 0 01-4 4h-4a4 4 0 01-4-4V8z" /></>,
  },
  {
    title: 'A checked Test Library',
    text: 'Playwright specs and Postman collections are checked the moment you drop them in. Nothing is saved until you confirm.',
    icon: <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6" /><path d="M9 15l2 2 4-4" /></>,
  },
  {
    title: 'Secure by default',
    text: 'Two-step verification with any authenticator app, encrypted tokens, and single use recovery codes.',
    icon: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  },
];

const STEPS = [
  { title: 'Connect', text: 'Sign in with GitHub, approve Jira, and pick the repository Verixa should watch.' },
  { title: 'Add your tests', text: 'Drop in Playwright specs and a Postman collection. Every file is checked first.' },
  { title: 'Get a verdict', text: 'Each pull request is tested and investigated, with bugs filed before anyone merges.' },
];

function Heading({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <Reveal className="section-head">
      <div className="eyebrow">{eyebrow}</div>
      <h2>{title}</h2>
      <p>{text}</p>
    </Reveal>
  );
}

export default function Features() {
  return (
    <>
      <section className="section" id="product">
        <Heading eyebrow="Product" title="One agent, watching every pull request."
                 text="Verixa plugs into your GitHub repository and takes the QA loop off your plate, before a human ever has to look." />
        <div className="feature-grid">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={(i % 3) as 0 | 1 | 2} className="feature">
              <span className="feature-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">{f.icon}</svg>
              </span>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="section" id="steps">
        <Heading eyebrow="How it works" title="Three steps to your first verdict."
                 text="Most teams are set up in a few minutes. There is nothing to install in your pipeline." />
        <ol className="steps">
          {STEPS.map((s, i) => (
            <Reveal key={s.title} delay={i as 0 | 1 | 2} className="step">
              <span className="step-num">0{i + 1}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </Reveal>
          ))}
        </ol>
      </section>
    </>
  );
}
