import { Fragment, lazy, Suspense, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import ShaderBackground from './ShaderBackground'
import useVoiceSearch from '../../hooks/useVoiceSearch'
import './landing.css'

// `three` is a real chunk of weight for a decorative flourish — lazy-loaded
// so it can't slow down first paint of the search box itself, which is the
// one thing on this page that actually has to be fast.
const WireframeCubes = lazy(() => import('./WireframeCubes'))

// ---------- content data ----------
// Every module/route/metric named below exists in the running app (see
// backend/nlp/chat_tools.py's tool schema and App.jsx's routes) — nothing
// here is aspirational copy for a capability that isn't wired up yet.

const EXAMPLES = [
  { label: 'Give me an innovative NLP project', prompt: 'Give me an innovative NLP project.' },
  { label: 'I have Python and React skills', prompt: 'I have Python and React skills — what should I build?' },
  { label: 'Find projects for a 3-month capstone', prompt: 'Find me a project for a 3-month capstone.' },
  // A real idea needs more than a one-line prompt to check — this one goes
  // straight to the actual Idea Check page instead of firing an empty chat turn.
  { label: 'Check this project idea', to: '/uniqueness' },
]

const WHAT_FLOW = ['Discover', 'Create', 'Evaluate', 'Compare', 'Select', 'Plan', 'Build']

const STATS = [
  { value: '500+', label: 'Projects indexed' },
  { value: '384', label: 'Embedding dimensions' },
  { value: '0.892', label: 'nDCG@5, measured' },
  { value: 'Hybrid', label: 'Semantic + keyword retrieval' },
]

const TRUST_POINTS = [
  'Real project catalogue',
  'Hybrid semantic + keyword retrieval',
  'Measured retrieval performance',
  'Every generated idea is checked against the catalogue',
]

const DISCOVER_FLOW = ['User Request', 'Hybrid Search', 'Semantic + Keyword Retrieval', 'Real Project Catalogue', 'Ranked Results']
const IDEATE_FLOW = ['User Requirements', 'AI Generates New Ideas', 'Originality Validation', 'Evaluation', 'Compare', 'Plan']

const HOW_IT_WORKS = [
  { n: '01', title: 'Describe what you want', body: 'A topic, your skills, a timeline — or nothing at all.' },
  { n: '02', title: 'AI understands your intent', body: 'It decides whether you need to discover or to generate.' },
  { n: '03', title: 'Discover or generate', body: 'Real catalogue projects via hybrid search, or original concepts validated as they’re built.' },
  { n: '04', title: 'Validate and compare', body: 'Originality score, side-by-side comparison, skill gap, difficulty and timeline.' },
  { n: '05', title: 'Select your project', body: 'One click carries it into a persistent workspace.' },
  { n: '06', title: 'Build your roadmap', body: 'Phase-by-phase plan, a synopsis, and a team if you need one.' },
]

const THINK_FLOW = ['User Request', 'Intent Understanding', 'RAG / Hybrid Retrieval', 'AI Reasoning', 'Tools', 'Validation', 'Personalized Result']

const CAPABILITIES = [
  { group: 'Discovery', icon: 'manage_search', title: 'Project Discovery', body: 'Describe what you want; dense embeddings and BM25 rank the real catalogue together.' },
  { group: 'Ideation', icon: 'auto_awesome', title: 'New Idea Generation', body: 'No idea yet? The assistant invents original concepts, validated before you see them.' },
  { group: 'Ideation', icon: 'fingerprint', title: 'Idea Check / Uniqueness', body: 'Originality score, overlapping concepts, and ranked similar projects for an idea of your own.', to: '/uniqueness' },
  { group: 'Evaluation', icon: 'compare_arrows', title: 'Project Comparison', body: 'Difficulty, duration, technologies and required skills, side by side.' },
  { group: 'Evaluation', icon: 'route', title: 'Project Decision Engine', body: 'Skill fit, timeline fit and catalogue uniqueness combined into one recommendation.' },
  { group: 'Evaluation', icon: 'checklist', title: 'Skill Gap Analysis', body: 'What you already have, versus what a specific project still requires.' },
  { group: 'Personalization', icon: 'badge', title: 'Résumé Match', body: 'Upload a résumé; get catalogue projects ranked against your detected skills.', to: '/resume-match' },
  { group: 'Planning', icon: 'schedule', title: 'Timeline Prediction', body: 'A duration estimate driven by team size and experience level.' },
  { group: 'Planning', icon: 'map', title: 'Roadmap & Synopsis', body: 'A phase-by-phase build plan, generated for the project you picked.' },
  { group: 'Collaboration', icon: 'groups', title: 'Team Workspaces', body: 'Invite-code teams, a shared board, and skill-matched role suggestions.', to: '/teams' },
  { group: 'Collaboration', icon: 'forum', title: 'AI Project Chat', body: 'One conversation that searches, compares, evaluates and plans — behind every module here.' },
]

const PLANNING_FLOW = ['Select Project', 'Skill Gap', 'Difficulty', 'Timeline', 'Roadmap', 'Team', 'Decision']

const DECISION_QUESTIONS = [
  'Which one should I choose?',
  'Which is easiest?',
  'Which fits my skills?',
  'Which is more unique?',
  'Give me your final recommendation',
]

const GENERIC_FLOW = ['Prompt', 'LLM Response', 'Possible Generic Recommendation']
const PROJECTMIND_FLOW = ['User Request', 'Intent', 'Real Project Knowledge', 'Hybrid Retrieval / Generation', 'AI Reasoning', 'Validation', 'Skill + Timeline Analysis', 'Roadmap']

const USE_CASES = [
  { icon: 'school', title: 'Students', quote: 'Find a realistic final-year project that matches your skills and timeline.' },
  { icon: 'code', title: 'Developers', quote: 'Explore catalogue projects that fit the stack you already know.' },
  { icon: 'groups', title: 'Teams', quote: 'Choose a project that fits everyone’s combined skills, not just one person’s.' },
  { icon: 'science', title: 'Builders & Researchers', quote: 'Generate and validate an original idea before committing weeks to it.' },
]

const TIMELINE = [
  {
    tag: 'Core',
    title: 'Hybrid Retrieval Engine',
    body: 'Dense sentence embeddings fused with BM25 keyword scoring, filtered before ranking so a domain or difficulty filter never returns an empty page.',
  },
  {
    tag: 'Planning',
    title: 'AI Project Planning',
    body: 'Synopsis and roadmap generation, personalised timeline prediction by team size and experience, and a project-grounded chat assistant.',
  },
  {
    tag: 'Collaboration',
    title: 'Team Collaboration',
    body: 'Résumé-matched recommendations, invite-code team workspaces, and a shared board to coordinate who is building what.',
  },
]

const FOOTER_PRODUCT = [
  { label: 'Discover', to: '/' },
  { label: 'Idea Check', to: '/uniqueness' },
  { label: 'Résumé Match', to: '/resume-match' },
  { label: 'Teams', to: '/teams' },
]

const FOOTER_RESOURCES = [
  { label: 'How It Works', to: '#how-it-works' },
  { label: 'Capabilities', to: '#capabilities' },
  { label: 'Architecture', to: '#architecture' },
]

/**
 * useIntersectionReveal — toggles .visible on each .stagger-item inside
 * `containerRef` as it scrolls into view, with a small stagger delay based
 * on position. Scoped to this component's own DOM subtree via `containerRef`
 * rather than querying the whole document, so it picks up every section
 * below without any per-section wiring.
 */
function useIntersectionReveal(containerRef) {
  useEffect(() => {
    const root = containerRef.current
    if (!root) return

    const items = Array.from(root.querySelectorAll('.stagger-item'))
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry, index) => {
          if (entry.isIntersecting) {
            setTimeout(() => entry.target.classList.add('visible'), index * 60)
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.1 },
    )
    items.forEach((item) => observer.observe(item))
    return () => observer.disconnect()
  }, [containerRef])
}

function StatRow({ icon, children }) {
  return (
    <div
      className="flex items-center gap-3 pb-2 t-label-mono"
      style={{ borderBottom: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)' }}
    >
      <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 18 }}>
        {icon}
      </span>
      <span>{children}</span>
    </div>
  )
}

/** Shared "A -> B -> C" pipeline chip chain — every step diagram in this page
 * (ideation, discovery, planning, decision, generic-vs-projectmind) reuses
 * this instead of one-off flex markup per section. */
function FlowChain({ steps, direction = 'horizontal', emphasis = false, nowrap = false, className = '' }) {
  const arrow = direction === 'vertical' ? '↓' : '→'
  return (
    <div className={`flow-chain ${direction === 'vertical' ? 'vertical' : ''} ${nowrap ? 'nowrap' : ''} ${className}`}>
      {steps.map((step, index) => (
        <Fragment key={step}>
          <span className={`flow-step${emphasis ? ' emphasis' : ''}`}>{step}</span>
          {index < steps.length - 1 && (
            <span className="flow-arrow" aria-hidden="true">
              {arrow}
            </span>
          )}
        </Fragment>
      ))}
    </div>
  )
}

function SectionTag({ children }) {
  return (
    <span
      className="t-label-caps mb-6 inline-block self-start px-3 py-1"
      style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)' }}
    >
      {children}
    </span>
  )
}

function CapabilityCard({ group, icon, index, title, body, to }) {
  const content = (
    <>
      <div className="mb-4 flex items-start justify-between">
        <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 24 }}>
          {icon}
        </span>
        <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
          {String(index + 1).padStart(2, '0')}
        </span>
      </div>
      <p className="cap-group mb-1">{group}</p>
      <h3 className="t-label-mono mb-1.5" style={{ color: 'var(--on-surface)', fontSize: 14 }}>
        {title}
      </h3>
      <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5, lineHeight: 1.5 }}>
        {body}
      </p>
    </>
  )
  const style = { borderRadius: 8 }
  if (to) {
    return (
      <Link to={to} className="glass-panel card-hover stagger-item block h-full p-5" style={style}>
        {content}
      </Link>
    )
  }
  return (
    <div className="glass-panel card-hover stagger-item h-full p-5" style={style}>
      {content}
    </div>
  )
}

function UseCaseCard({ icon, title, quote }) {
  return (
    <div className="glass-panel card-hover stagger-item h-full p-5" style={{ borderRadius: 8 }}>
      <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 22 }}>
        {icon}
      </span>
      <h3 className="t-label-caps mt-3" style={{ color: 'var(--on-surface)', fontSize: 11 }}>
        {title}
      </h3>
      <p className="t-body-md mt-2" style={{ color: 'var(--on-surface-variant)', fontSize: 13.5, lineHeight: 1.5 }}>
        “{quote}”
      </p>
    </div>
  )
}

/** Static mock of a real chat turn — same field names, labels and classes as
 * Dashboard.jsx's GeneratedIdeaCard (generate_project_ideas tool), just with
 * illustrative example content instead of a live conversation. Action chips
 * are inert <span>s, not <button>s, so the preview never implies an
 * affordance that doesn't do anything on this page. */
function PreviewChatMock() {
  const actions = ['Explore Idea', 'Check Uniqueness', 'Compare', 'Create Roadmap']
  return (
    <div className="glass-panel stagger-item p-6 sm:p-7" style={{ borderRadius: 8 }}>
      <p className="t-label-caps mb-4" style={{ color: 'var(--outline)', fontSize: 10 }}>
        AI Project Chat
      </p>
      <div className="flex flex-col gap-4">
        <div className="stagger-item flex justify-end">
          <div
            className="max-w-[85%] px-3.5 py-2.5 text-sm leading-relaxed"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
          >
            Give me an innovative NLP project for a 3-month capstone.
          </div>
        </div>

        <div
          className="stagger-item w-fit max-w-full px-3.5 py-2.5 text-sm leading-relaxed"
          style={{ background: 'var(--surface-container-low)', color: 'var(--on-surface-variant)', border: '1px solid var(--border-technical)', borderRadius: 8 }}
        >
          Here’s something that doesn’t exist in the catalogue yet:
        </div>

        <div className="stagger-item w-full p-4" style={{ border: '1px solid var(--primary)', background: 'rgba(14,16,15,0.7)', borderRadius: 8 }}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="t-label-caps px-2 py-1" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 999, fontSize: 9.5 }}>
              AI Generated Project Idea
            </span>
            <span className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 12 }}>
              84% original
            </span>
          </div>

          <h3 className="t-label-mono mt-2.5" style={{ color: 'var(--on-surface)', fontSize: 15 }}>
            AI Codebase Understanding Assistant
          </h3>
          <p className="t-label-mono mt-0.5" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
            Advanced · Software Engineering · ~10 weeks
          </p>

          <div className="mt-3 space-y-2">
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
                Problem
              </p>
              <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                Developers spend hours re-orienting themselves in an unfamiliar codebase before making one safe change.
              </p>
            </div>
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
                Solution
              </p>
              <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                Parse the repository into a symbol graph, embed it, and let a retrieval-grounded assistant answer “where” and “why” questions about the code.
              </p>
            </div>
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
                Why it’s different
              </p>
              <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                Answers cite the exact file and line, grounded in the graph — not paraphrased from the model’s memory.
              </p>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {['Python', 'tree-sitter', 'FAISS', 'LangChain'].map((t) => (
              <span key={t} className="gm-chip px-2 py-1">
                {t}
              </span>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {actions.map((label) => (
              <span
                key={label}
                className="t-label-caps px-2.5 py-1.5"
                style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 10, borderRadius: 6 }}
              >
                {label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

/** Second, smaller preview: Compare -> Skill Gap -> Timeline -> Roadmap, in
 * the exact table/bar layout Dashboard.jsx's ComparisonBlock/SkillGapBlock
 * use. The two project titles are real catalogue projects (confirmed against
 * the live database), not invented ones — everything else on the strip
 * (skill %, timeline, roadmap phase names) is illustrative UI, not a claim
 * about a specific real query. */
function PreviewCompareStrip() {
  const columns = [
    { title: 'Topic Modelling of Customer Support Tickets', difficulty: 'Intermediate', duration: '6 weeks', tech: 'Python, Gensim, spaCy' },
    { title: 'Spam SMS Classification', difficulty: 'Beginner', duration: '4 weeks', tech: 'Python, scikit-learn, NLTK' },
  ]
  const rows = [
    { label: 'Difficulty', get: (c) => c.difficulty },
    { label: 'Duration', get: (c) => c.duration },
    { label: 'Technologies', get: (c) => c.tech },
  ]
  return (
    <div className="glass-panel stagger-item p-6 sm:p-7" style={{ borderRadius: 8, borderColor: 'var(--outline-variant)' }}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <span className="t-label-caps px-2 py-1" style={{ border: '1px solid var(--outline-variant)', color: 'var(--on-surface-variant)', borderRadius: 999, fontSize: 9.5 }}>
          Comparison Workspace
        </span>
      </div>
      <p className="t-label-caps mb-4" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Compare → Skill Gap → Timeline → Roadmap
      </p>

      <div className="w-full overflow-x-auto">
        <table className="w-full text-left" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th className="pb-2 pr-4" />
              {columns.map((c) => (
                <th key={c.title} className="t-label-mono pb-2 pr-4 align-top" style={{ color: 'var(--primary)', fontSize: 12.5 }}>
                  {c.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} style={{ borderTop: '1px solid var(--border-technical)' }}>
                <td className="t-label-caps py-2 pr-4" style={{ color: 'var(--outline)', fontSize: 10, whiteSpace: 'nowrap' }}>
                  {row.label}
                </td>
                {columns.map((c) => (
                  <td key={c.title} className="t-body-md py-2 pr-4" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                    {row.get(c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p className="t-label-caps mb-1.5" style={{ color: 'var(--outline)', fontSize: 10 }}>
            Skill Gap
          </p>
          <div className="flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
              <div className="h-full rounded-full" style={{ background: 'var(--primary)', width: '62%' }} />
            </div>
            <span className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12 }}>
              62% ready
            </span>
          </div>
        </div>
        <div>
          <p className="t-label-caps mb-1.5" style={{ color: 'var(--outline)', fontSize: 10 }}>
            Timeline
          </p>
          <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 13 }}>
            8 weeks <span style={{ color: 'var(--outline)', fontSize: 11.5 }}>(2 people, intermediate)</span>
          </p>
        </div>
      </div>

      <div className="mt-4">
        <p className="t-label-caps mb-1.5" style={{ color: 'var(--outline)', fontSize: 10 }}>
          Roadmap
        </p>
        <FlowChain steps={['Setup & Data', 'Core Build', 'Polish & Ship']} />
      </div>
    </div>
  )
}

export default function LandingHero({ value, onChange, onSubmit }) {
  const rootRef = useRef(null)
  useIntersectionReveal(rootRef)

  const { supported: voiceSupported, listening, start, stop } = useVoiceSearch()

  // Every chat-bound CTA on this page (hero examples, the ideation path
  // button, the final CTA) goes through the exact same gate Search.jsx
  // already wires up via `onSubmit` — nothing here talks to the backend or
  // the auth gate directly.
  const runPrompt = (text) => {
    onChange(text)
    onSubmit(text)
  }

  const submit = (event) => {
    event.preventDefault()
    onSubmit()
  }

  return (
    <div ref={rootRef} className="landing-mono">
      {/* ---------- hero ---------- */}
      <section className="relative flex min-h-[88vh] flex-col items-center justify-center overflow-hidden px-6 pt-16">
        <div className="pointer-events-none absolute inset-0 z-0 opacity-40">
          <ShaderBackground className="h-full w-full" />
        </div>
        <div
          className="pointer-events-none absolute inset-0 z-0 flex items-center justify-center opacity-90"
          aria-hidden="true"
        >
          <Suspense fallback={null}>
            <WireframeCubes className="h-[600px] max-h-full w-[600px] max-w-full" />
          </Suspense>
        </div>
        <div
          className="pointer-events-none absolute inset-0 z-0"
          style={{ background: 'linear-gradient(to bottom, transparent, rgba(0,0,0,0.72) 80%, #000 100%)' }}
        />

        <div className="stagger-item relative z-10 flex w-full max-w-3xl flex-col items-center">
          <span
            className="t-label-caps mb-6 rounded-full px-3 py-1"
            style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)', color: 'var(--on-surface-variant)' }}
          >
            Hybrid semantic + keyword search · 500 projects indexed
          </span>

          <h1 className="t-headline-xl mb-5 text-center" style={{ color: 'var(--primary)' }}>
            Describe.
            <br />
            <span style={{ color: 'var(--on-surface-variant)' }}>Discover.</span>
          </h1>

          <p className="t-body-lg mb-8 max-w-xl text-center" style={{ color: 'var(--on-surface-variant)' }}>
            Discover a real project, or generate a new one — then validate it, compare it,
            and plan exactly how to build it. One conversation, grounded in a real catalogue.
          </p>

          <form onSubmit={submit} className="shimmer-border hero-input-shell w-full rounded bg-black" style={{ borderRadius: 8 }}>
            <div className="relative">
              <span
                className="material-symbols-outlined pointer-events-none absolute left-5 top-1/2 -translate-y-1/2"
                style={{ color: 'var(--on-surface-variant)' }}
                aria-hidden="true"
              >
                auto_awesome
              </span>
              <input
                value={value}
                onChange={(e) => onChange(e.target.value)}
                autoFocus
                placeholder="Describe the project you want to build…"
                aria-label="Search or describe a project"
                className="glass-panel t-body-lg w-full rounded py-5 pl-14 pr-32 outline-none"
                style={{ color: 'var(--primary)', borderRadius: 8, caretColor: 'var(--primary)' }}
              />
              <div className="absolute inset-y-0 right-3 flex items-center gap-1.5">
                {voiceSupported && (
                  <button
                    type="button"
                    onClick={() => (listening ? stop() : start(onChange))}
                    aria-label={listening ? 'Stop voice search' : 'Search by voice'}
                    aria-pressed={listening}
                    className="grid h-9 w-9 place-items-center transition"
                    style={{
                      color: listening ? 'var(--primary)' : 'var(--on-surface-variant)',
                      background: 'var(--surface-container)',
                      border: '1px solid var(--border-technical)',
                      borderRadius: 8,
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
                      mic
                    </span>
                  </button>
                )}
                <button
                  type="submit"
                  aria-label="Describe my project — run search"
                  className="t-label-caps flex h-10 items-center gap-1.5 px-4 transition hover:opacity-85 active:scale-[0.97]"
                  style={{ color: 'var(--on-primary)', background: 'var(--primary)', borderRadius: 8, fontSize: 11 }}
                >
                  Describe
                  <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                    arrow_forward
                  </span>
                </button>
              </div>
            </div>
          </form>

          <div className="mt-4 flex items-center gap-4 t-label-mono" style={{ color: 'var(--on-surface-variant)' }}>
            <span className="rounded-sm px-2 py-1" style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)' }}>
              Press Enter
            </span>
            <span>to run semantic search.</span>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {EXAMPLES.map((example) =>
              example.to ? (
                <Link
                  key={example.label}
                  to={example.to}
                  className="t-label-mono rounded-full px-3 py-1.5 transition hover:border-white/40 hover:bg-white/5"
                  style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)' }}
                >
                  {example.label}
                </Link>
              ) : (
                <button
                  key={example.label}
                  type="button"
                  onClick={() => runPrompt(example.prompt)}
                  className="t-label-mono rounded-full px-3 py-1.5 transition hover:border-white/40 hover:bg-white/5"
                  style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)' }}
                >
                  {example.label}
                </button>
              ),
            )}
          </div>

          <button
            type="button"
            onClick={() => runPrompt('Give me an innovative project idea based on my interests.')}
            className="btn-secondary t-label-caps mt-5 flex items-center gap-1.5 px-4 py-2"
            style={{ fontSize: 10.5 }}
          >
            Don’t have an idea? Generate one
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
              arrow_forward
            </span>
          </button>
        </div>

        <div className="absolute bottom-8 z-10 animate-bounce" style={{ color: 'var(--on-surface-variant)' }} aria-hidden="true">
          <span className="material-symbols-outlined">south</span>
        </div>
      </section>

      {/* ---------- what is projectmind (product value) ---------- */}
      <section className="container-wide py-16" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <div className="stagger-item mx-auto max-w-3xl text-center">
          <SectionTag>What is ProjectMind?</SectionTag>
          <h2 className="t-headline-lg mx-auto" style={{ color: 'var(--primary)' }}>
            From “What should I build?” to “Here’s exactly how to build it.”
          </h2>
          <p className="t-body-md mx-auto mt-5 max-w-xl" style={{ color: 'var(--on-surface-variant)' }}>
            A project-planning assistant, not a generic chatbot — every answer traces back to a
            real catalogue and a real tool, never a guess at what a “good project” looks like.
          </p>
        </div>
        <div className="stagger-item mt-10 flex justify-center">
          <FlowChain steps={WHAT_FLOW} />
        </div>
      </section>

      {/* ---------- trust metrics ---------- */}
      <section className="py-12" style={{ background: 'var(--surface-container-low)' }}>
        <div className="container-wide grid grid-cols-2 gap-x-6 gap-y-8 lg:grid-cols-4">
          {STATS.map((stat) => (
            <div key={stat.label} className="stagger-item text-center lg:text-left">
              <p className="t-headline-lg" style={{ color: 'var(--primary)', fontFamily: "'JetBrains Mono', monospace" }}>
                {stat.value}
              </p>
              <p className="t-label-caps mt-1" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
                {stat.label}
              </p>
            </div>
          ))}
        </div>
        <div className="container-wide stagger-item mt-8 flex flex-wrap gap-x-8 gap-y-3 border-t pt-6" style={{ borderColor: 'var(--border-technical)' }}>
          {TRUST_POINTS.map((point) => (
            <span key={point} className="trust-check">
              <span className="material-symbols-outlined" aria-hidden="true">
                check_circle
              </span>
              {point}
            </span>
          ))}
        </div>
      </section>

      {/* ---------- two ways to start ---------- */}
      <section className="container-wide py-16">
        <div className="stagger-item mb-10 text-center">
          <SectionTag>Two ways to start</SectionTag>
          <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
            Bring an idea, or borrow ours.
          </h2>
        </div>
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="glass-panel stagger-item flex flex-col p-8" style={{ borderRadius: 8 }}>
            <span className="t-label-caps mb-4 self-start px-2.5 py-1" style={{ border: '1px solid var(--primary)', color: 'var(--primary)', borderRadius: 999, fontSize: 10 }}>
              Path A
            </span>
            <h3 className="t-headline-md mb-2" style={{ color: 'var(--primary)' }}>
              I have an idea
            </h3>
            <p className="t-body-md mb-6" style={{ color: 'var(--on-surface-variant)' }}>
              Check how original it is against the real catalogue, then compare it, evaluate it, and plan it.
            </p>
            <FlowChain steps={['Idea', 'Discover Similar', 'Check Originality', 'Compare', 'Evaluate', 'Plan']} className="mb-6" />
            <Link to="/uniqueness" className="btn-primary t-label-caps mt-auto w-fit px-4 py-2.5">
              Check My Idea
            </Link>
          </div>

          <div className="glass-panel stagger-item flex flex-col p-8" style={{ borderRadius: 8 }}>
            <span className="t-label-caps mb-4 self-start px-2.5 py-1" style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 999, fontSize: 10 }}>
              Path B
            </span>
            <h3 className="t-headline-md mb-2" style={{ color: 'var(--primary)' }}>
              I need an idea
            </h3>
            <p className="t-body-md mb-6" style={{ color: 'var(--on-surface-variant)' }}>
              Tell it your interests, skills, or time budget — it generates original concepts and validates them for you.
            </p>
            <FlowChain steps={['Requirements', 'AI Generates Ideas', 'Originality Validation', 'Evaluation', 'Compare', 'Plan']} className="mb-6" />
            <button
              type="button"
              onClick={() => runPrompt('I don’t have a project idea yet — generate one for me.')}
              className="btn-secondary t-label-caps mt-auto w-fit px-4 py-2.5"
            >
              Generate An Idea
            </button>
          </div>
        </div>
      </section>

      {/* ---------- real product preview ---------- */}
      <section className="container-wide py-16" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <div className="stagger-item mb-10 max-w-2xl">
          <SectionTag>See it in action</SectionTag>
          <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
            A real conversation, not a mockup.
          </h2>
          <p className="t-body-md mt-4" style={{ color: 'var(--on-surface-variant)' }}>
            Built from the app’s own chat components — the fields, labels and layout below are
            exactly what the assistant returns.
          </p>
        </div>
        <div className="grid gap-6 xl:grid-cols-2">
          <PreviewChatMock />
          <PreviewCompareStrip />
        </div>
      </section>

      {/* ---------- how projectmind works (user workflow) ---------- */}
      <section id="how-it-works" className="py-16" style={{ background: 'var(--surface-container-low)' }}>
        <div className="container-wide">
          <div className="stagger-item mb-10">
            <SectionTag>How ProjectMind works</SectionTag>
            <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
              Six steps, one conversation.
            </h2>
          </div>
          <div className="grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
            {HOW_IT_WORKS.map((step) => (
              <div key={step.n} className="stagger-item" style={{ borderTop: '2px solid var(--border-technical)', paddingTop: 16 }}>
                <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 13 }}>
                  {step.n}
                </span>
                <h3 className="t-label-mono mt-2" style={{ color: 'var(--primary)', fontSize: 15 }}>
                  {step.title}
                </h3>
                <p className="t-body-md mt-1.5" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
                  {step.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- discovery + ideation engines (grounded: discovery vs ideation) ---------- */}
      <section className="container-wide py-16">
        <div className="stagger-item mb-10 text-center">
          <SectionTag>Grounded either way</SectionTag>
          <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
            Two engines, one assistant.
          </h2>
        </div>
        <div className="grid gap-10 lg:grid-cols-2">
          <div className="stagger-item">
            <h3 className="t-headline-md mb-3" style={{ color: 'var(--primary)' }}>
              Existing Project Discovery
            </h3>
            <p className="t-body-md mb-6" style={{ color: 'var(--on-surface-variant)' }}>
              These results are real catalogue projects, ranked — never invented.
            </p>
            <FlowChain steps={DISCOVER_FLOW} direction="vertical" />
          </div>
          <div className="stagger-item">
            <h3 className="t-headline-md mb-3" style={{ color: 'var(--primary)' }}>
              New Project Ideation
            </h3>
            <p className="t-body-md mb-6" style={{ color: 'var(--on-surface-variant)' }}>
              Generated concepts are scored for originality relative to the ProjectMind
              catalogue — not a claim of global uniqueness.
            </p>
            <FlowChain steps={IDEATE_FLOW} direction="vertical" />
          </div>
        </div>
      </section>

      {/* ---------- how projectmind thinks / architecture (technical architecture) ---------- */}
      <section id="architecture" className="py-16" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <div className="container-wide">
          <div className="stagger-item mb-6 max-w-3xl">
            <SectionTag>How ProjectMind thinks</SectionTag>
            <p className="t-body-md mb-6" style={{ color: 'var(--on-surface-variant)' }}>
              One layer beneath the conversation, every answer is resolved through retrieval and
              tool calls — never recalled from the model’s memory:
            </p>
          </div>
          {/* Full container width (not the text column's max-w-3xl) and
              nowrap+scroll so this chain reads as one continuous pipeline —
              a flex-wrap here would strand a trailing arrow at the end of a
              line with nothing visually following it. */}
          <div className="stagger-item mb-10 overflow-x-auto pb-1">
            <FlowChain steps={THINK_FLOW} nowrap />
          </div>

          <div className="grid gap-10 lg:grid-cols-2 lg:items-start">
            <div className="stagger-item">
              <h2 className="t-headline-lg mb-6" style={{ color: 'var(--primary)' }}>
                Hybrid Retrieval Engine
              </h2>
              <p className="t-body-md mb-8 max-w-md" style={{ color: 'var(--on-surface-variant)' }}>
                Dense embeddings capture what a query means; BM25 catches the exact technical
                tokens embeddings miss — model names, framework versions, acronyms. Neither wins
                alone. Filters apply before ranking, not after, so a difficulty or domain filter
                never quietly returns nothing.
              </p>
              <div className="flex flex-col gap-4">
                <StatRow icon="database">500 projects indexed</StatRow>
                <StatRow icon="memory">384-dimension embedding space</StatRow>
                <StatRow icon="bolt">0.892 nDCG@5, measured — not guessed</StatRow>
              </div>
            </div>

            <div className="glass-panel stagger-item relative overflow-hidden p-6" style={{ borderRadius: 8 }}>
              <div className="relative z-10 flex flex-col gap-4 t-label-mono" style={{ color: 'var(--primary)' }}>
                <div
                  className="flex items-center justify-between p-4"
                  style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-container)' }}
                >
                  <span>Query Input</span>
                  <span className="material-symbols-outlined">data_object</span>
                </div>
                <div className="flex justify-center">
                  <div className="h-5 w-px" style={{ background: 'var(--border-technical)' }} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 text-center" style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)' }}>
                    Dense Encoding
                  </div>
                  <div className="p-4 text-center" style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)' }}>
                    BM25 Tokens
                  </div>
                </div>
                <div className="flex justify-center">
                  <div className="h-5 w-px" style={{ background: 'var(--border-technical)' }} />
                </div>
                <div
                  className="p-4 text-center"
                  style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-container)' }}
                >
                  Fusion
                </div>
                <div className="flex justify-center">
                  <div className="h-5 w-px" style={{ background: 'var(--border-technical)' }} />
                </div>
                <div
                  className="shimmer-border p-4 text-center"
                  style={{ border: '1px solid var(--primary)', background: 'var(--surface-container-highest)' }}
                >
                  Filtered Ranking → Project Results
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- why different (competitive advantage) ---------- */}
      <section className="py-16" style={{ background: 'var(--surface-container-low)' }}>
        <div className="container-wide">
          <div className="stagger-item mb-10 text-center">
            <SectionTag>Why ProjectMind is different</SectionTag>
            <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
              Why not just ask a generic AI?
            </h2>
            <p className="t-body-md mx-auto mt-4 max-w-xl" style={{ color: 'var(--on-surface-variant)' }}>
              A general-purpose assistant can talk about projects. This one answers from a
              catalogue it can point to and tools it actually calls.
            </p>
          </div>
          <div className="grid gap-8 lg:grid-cols-2">
            <div className="stagger-item">
              <p className="t-label-caps mb-4" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
                Generic AI
              </p>
              <FlowChain steps={GENERIC_FLOW} direction="vertical" />
            </div>
            <div className="stagger-item">
              <p className="t-label-caps mb-4" style={{ color: 'var(--primary)', fontSize: 10.5 }}>
                ProjectMind
              </p>
              <FlowChain steps={PROJECTMIND_FLOW} direction="vertical" emphasis />
            </div>
          </div>
        </div>
      </section>

      {/* ---------- product capabilities (actual features) ---------- */}
      <section id="capabilities" className="container-wide py-16">
        <div className="stagger-item mb-10 text-center">
          <SectionTag>Product capabilities</SectionTag>
          <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
            Everything that's actually here.
          </h2>
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {CAPABILITIES.map((cap, index) => (
            <CapabilityCard key={cap.title} index={index} {...cap} />
          ))}
        </div>
      </section>

      {/* ---------- ai project planning -> decision engine (one progression) ---------- */}
      <section className="py-16" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <div className="container-wide grid gap-10 lg:grid-cols-2 lg:items-center">
          <div className="stagger-item">
            <SectionTag>AI project planning</SectionTag>
            <h2 className="t-headline-lg mb-4" style={{ color: 'var(--primary)' }}>
              It doesn't stop at finding a project.
            </h2>
            <p className="t-body-md" style={{ color: 'var(--on-surface-variant)' }}>
              Once you select one, ProjectMind helps answer two questions: “Can I actually build
              this?” and “How should I build it?” — ending, if you're weighing more than one, in
              a decision.
            </p>
          </div>
          <div className="stagger-item">
            <FlowChain steps={PLANNING_FLOW} direction="vertical" />
          </div>
        </div>
      </section>

      {/* ---------- decision engine (the culminating step) ---------- */}
      <section className="py-16" style={{ background: 'var(--surface-container-low)' }}>
        <div className="container-wide grid gap-10 lg:grid-cols-2 lg:items-center">
          <div className="stagger-item order-2 lg:order-1">
            <div className="flow-chain vertical">
              <span className="flow-step">Projects You're Comparing</span>
              <span className="flow-arrow" aria-hidden="true">↓</span>
              <div className="flow-chain">
                <span className="flow-step">Skill Fit</span>
                <span className="flow-arrow" aria-hidden="true">+</span>
                <span className="flow-step">Time Fit</span>
                <span className="flow-arrow" aria-hidden="true">+</span>
                <span className="flow-step">Catalogue Uniqueness</span>
              </div>
              <span className="flow-arrow" aria-hidden="true">↓</span>
              <div className="flow-callout">
                <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden="true">
                  bolt
                </span>
                Final Recommendation
              </div>
            </div>
          </div>
          <div className="stagger-item order-1 lg:order-2">
            <SectionTag>Project decision engine</SectionTag>
            <h2 className="t-headline-lg mb-4" style={{ color: 'var(--primary)' }}>
              “Which one should I choose?”
            </h2>
            <p className="t-body-md mb-6" style={{ color: 'var(--on-surface-variant)' }}>
              Ask it directly — it combines your skills, timeline fit and each project's
              catalogue uniqueness into one recommendation, with a runner-up.
            </p>
            <div className="flex flex-wrap gap-2">
              {DECISION_QUESTIONS.map((q) => (
                <span
                  key={q}
                  className="t-label-mono px-3 py-1.5"
                  style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 999 }}
                >
                  {q}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ---------- use cases ---------- */}
      <section className="container-wide py-16">
        <div className="stagger-item mb-10 text-center">
          <SectionTag>Who it's for</SectionTag>
          <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
            Built for anyone choosing what to build.
          </h2>
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {USE_CASES.map((uc) => (
            <UseCaseCard key={uc.title} {...uc} />
          ))}
        </div>
      </section>

      {/* ---------- timeline ---------- */}
      <section className="py-16" style={{ background: 'var(--surface-container-low)' }}>
        <div className="container-wide">
          <div className="stagger-item mb-10">
            <h2 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
              Platform Timeline
            </h2>
            <p className="t-body-md mt-4" style={{ color: 'var(--on-surface-variant)' }}>
              What's actually shipped, not a roadmap of promises.
            </p>
          </div>
          <div className="grid gap-8 md:grid-cols-3">
            {TIMELINE.map((item) => (
              <div key={item.title} className="stagger-item" style={{ borderTop: '2px solid var(--primary)', paddingTop: 20 }}>
                <div className="t-label-caps mb-2" style={{ color: 'var(--on-surface-variant)' }}>
                  {item.tag}
                </div>
                <h3 className="t-headline-md mb-2" style={{ color: 'var(--primary)' }}>
                  {item.title}
                </h3>
                <p className="t-body-md" style={{ color: 'var(--on-surface-variant)' }}>
                  {item.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- final cta ---------- */}
      <section className="container-wide py-16">
        <div
          className="glass-panel stagger-item mx-auto max-w-3xl p-10 text-center sm:p-14"
          style={{ borderRadius: 12, borderColor: 'var(--outline-variant)' }}
        >
          <h2 className="t-headline-lg mb-4" style={{ color: 'var(--primary)' }}>
            You have an idea.
            <br />
            Now find out what it takes to build it.
          </h2>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={() => document.querySelector('input[aria-label="Search or describe a project"]')?.focus()}
              className="btn-primary t-label-caps px-5 py-3"
            >
              Describe My Project
            </button>
            <button
              type="button"
              onClick={() => runPrompt('I don’t have a project idea yet — generate one for me.')}
              className="btn-secondary t-label-caps px-5 py-3"
            >
              Generate New Idea
            </button>
          </div>
        </div>
      </section>

      {/* ---------- footer ---------- */}
      <footer className="py-12" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <div className="container-wide flex flex-col gap-10 md:flex-row md:justify-between">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <span
                className="grid h-8 w-8 place-items-center text-xs font-bold"
                style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
              >
                PM
              </span>
              <span className="t-headline-md" style={{ color: 'var(--primary)', fontSize: 16 }}>
                ProjectMind AI
              </span>
            </div>
            <p className="t-label-mono mt-4" style={{ color: 'var(--outline)', fontSize: 12 }}>
              Discover · Create · Evaluate · Plan · Build
            </p>
          </div>

          <div className="grid grid-cols-2 gap-x-12 gap-y-8 sm:gap-x-16">
            <div>
              <p className="t-label-caps mb-3" style={{ color: 'var(--outline)', fontSize: 10 }}>
                Product
              </p>
              <ul className="space-y-2.5">
                {FOOTER_PRODUCT.map((link) => (
                  <li key={link.label}>
                    <Link to={link.to} className="t-label-mono transition hover:opacity-75" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="t-label-caps mb-3" style={{ color: 'var(--outline)', fontSize: 10 }}>
                Resources
              </p>
              <ul className="space-y-2.5">
                {FOOTER_RESOURCES.map((link) => (
                  <li key={link.label}>
                    <a href={link.to} className="t-label-mono transition hover:opacity-75" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}
