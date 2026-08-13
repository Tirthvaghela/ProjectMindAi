import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Modal from '../components/Modal'
import GeneratedIdeaCard from '../components/GeneratedIdeaCard'
import GettingStartedPanel from '../components/GettingStartedPanel'
import MarkdownLite from '../components/MarkdownLite'
import AuthGateModal from '../components/AuthGateModal'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

// Mirrors backend/nlp/ideation.py's IDEA_COUNT_DEFAULT / IDEA_COUNT_MAX —
// not read from an endpoint since neither is exposed as config, but this is
// just a UI bound on the picker; the backend still clamps independently.
const IDEA_COUNT_DEFAULT = 5
const IDEA_COUNT_MAX = 6

const STARTER_TOPICS = [
  'An innovative NLP project I can finish in 3 months',
  'Something in computer vision for a beginner',
  'An AI project that helps students study',
]

// Every option sends one natural-language instruction through the exact
// same pipeline the [Improve Idea] chip already uses in Dashboard.jsx
// (nlp/chat_tools.py:refine_project_idea, via general_reply's tool-calling
// loop) — no separate "refinement engine", just a friendlier way to compose
// the instruction than typing it out.
const REFINE_OPTIONS = [
  {
    key: 'innovative',
    label: 'More innovative',
    instruction: (name) => `Make "${name}" more innovative — a sharper, more original angle on the same core problem.`,
  },
  {
    key: 'easier',
    label: 'Easier to build',
    instruction: (name) => `Make "${name}" easier to build for a solo student, simplifying scope or technology where it helps.`,
  },
  {
    key: 'shorter',
    label: 'Reduce timeline',
    instruction: (name) => `Reduce the timeline for "${name}" — cut scope so it realistically fits in a shorter duration.`,
  },
  {
    key: 'add-ai',
    label: 'Add AI',
    instruction: (name) => `Add a genuine AI/ML component to "${name}".`,
  },
  {
    key: 'remove-ai',
    label: 'Remove AI',
    instruction: (name) => `Remove the AI/ML component from "${name}" and simplify it into a non-AI project.`,
  },
  {
    key: 'tech',
    label: 'Change technology',
    needsInput: true,
    placeholder: 'e.g. React instead of Vue',
    instruction: (name, input) => `Change "${name}" to use ${input} instead of its current technology stack.`,
  },
  {
    key: 'custom',
    label: 'Custom instruction',
    needsInput: true,
    placeholder: 'Describe what to change…',
    instruction: (name, input) => `For "${name}": ${input}`,
  },
]

const COMPARE_ROWS = [
  { label: 'Domain', get: (i) => i.domain },
  { label: 'Difficulty', get: (i) => i.difficulty },
  { label: 'Duration', get: (i) => `${i.duration_weeks} weeks` },
  { label: 'Originality', get: (i) => `${i.originality_score}%` },
  { label: 'Technologies', get: (i) => i.technologies?.join(', ') },
]

/** [Check Uniqueness] result — same fields UniquenessCheck.jsx renders (both
 * are backend/nlp/recommend.py:check_uniqueness via POST /api/uniqueness),
 * just re-run live for one generated idea instead of a hand-typed one. */
function UniquenessResult({ result }) {
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-baseline gap-3">
          <span className="t-headline-lg" style={{ color: 'var(--primary)' }}>{result.originality_score}%</span>
          <span className="t-label-mono" style={{ color: 'var(--on-surface-variant)' }}>
            {result.is_unique ? 'Looks original' : 'Project originality'}
          </span>
        </div>
        <p className="t-body-md mt-1.5" style={{ color: 'var(--outline)', fontSize: 12.5 }}>
          {result.is_unique
            ? 'No catalogue project is close enough by meaning to flag.'
            : `Closest match scored ${Math.round(result.highest_similarity * 100)}% similarity (flagged above ${Math.round(result.threshold * 100)}%).`}
        </p>

        {result.overlapping_concepts?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {result.overlapping_concepts.map((c) => (
              <span key={c} className="gm-chip px-2 py-1">{c}</span>
            ))}
          </div>
        )}

        {result.suggestions?.length > 0 && (
          <ul className="t-body-md mt-3 space-y-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
            {result.suggestions.map((s) => (
              <li key={s}>· {s}</li>
            ))}
          </ul>
        )}
      </div>

      {result.getting_started && <GettingStartedPanel plan={result.getting_started} />}

      {result.similar_projects?.length > 0 && (
        <div>
          <p className="t-label-caps mb-2" style={{ color: 'var(--outline)', fontSize: 10 }}>Closest catalogue projects</p>
          <div className="space-y-2">
            {result.similar_projects.slice(0, 5).map((p) => (
              <Link
                key={p.project_id}
                to={`/project/${p.project_id}`}
                className="flex items-center justify-between gap-3 px-3 py-2 transition hover:opacity-80"
                style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}
              >
                <span className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 13 }}>{p.title}</span>
                <span className="t-label-mono shrink-0" style={{ color: 'var(--outline)', fontSize: 11 }}>
                  {Math.round((p.similarity ?? 0) * 100)}% similar
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * The dedicated "New Project Ideation" workspace, built entirely on top of
 * the existing AI Ideation Engine (backend/nlp/ideation.py + chat_tools.py)
 * — no new backend endpoint. Idea generation, refinement, uniqueness
 * checking, and roadmapping all reach the model the same way Dashboard's
 * chat already does: one natural-language message through
 * api.sendConversationMessage on one running conversation, whose stored
 * blocks are what let the assistant resolve "the third one" or "can it be
 * done in 3 months" later without this page tracking any of that itself
 * (see nlp/ai_assistant.py:_shown_ideas_note). This page just gives that
 * pipeline a purpose-built surface — structured intake, idea cards, and
 * targeted actions — instead of a chat transcript.
 */
export default function Ideate() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [topic, setTopic] = useState('')
  const [domain, setDomain] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const [count, setCount] = useState(IDEA_COUNT_DEFAULT)
  const [domains, setDomains] = useState([])
  const [difficulties, setDifficulties] = useState([])

  const [conversationId, setConversationId] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [error, setError] = useState(null)
  const [ideas, setIdeas] = useState([])

  const [selectedIdeaId, setSelectedIdeaId] = useState(null)
  const [selectingId, setSelectingId] = useState(null)
  const [selectError, setSelectError] = useState(null)
  const [compareIds, setCompareIds] = useState(new Set())
  const [showCompare, setShowCompare] = useState(false)

  const [refineTarget, setRefineTarget] = useState(null)
  const [refineOptionKey, setRefineOptionKey] = useState(null)
  const [refineInput, setRefineInput] = useState('')
  const [refineBusy, setRefineBusy] = useState(false)
  const [refineError, setRefineError] = useState(null)

  const [uniquenessTarget, setUniquenessTarget] = useState(null)
  const [uniquenessStatus, setUniquenessStatus] = useState('idle')
  const [uniquenessResult, setUniquenessResult] = useState(null)
  const [uniquenessError, setUniquenessError] = useState(null)

  const [roadmapTarget, setRoadmapTarget] = useState(null)
  const [roadmapStatus, setRoadmapStatus] = useState('idle')
  const [roadmapText, setRoadmapText] = useState('')

  const [followUpText, setFollowUpText] = useState('')
  const [followUpThread, setFollowUpThread] = useState([])
  const [followUpBusy, setFollowUpBusy] = useState(false)

  const [authGateOpen, setAuthGateOpen] = useState(false)
  const gatedActionRef = useRef(null)

  useEffect(() => {
    api
      .filters()
      .then(({ data }) => {
        setDomains(data.domains ?? [])
        setDifficulties(data.difficulties ?? [])
      })
      .catch(() => {})
  }, [])

  // Every message-sending action gates the same way Dashboard's composer
  // does — a signed-out visitor gets the sign-in modal, and whatever they
  // were doing fires immediately after (see AuthGateModal below).
  const withAuth = (fn) => (...args) => {
    if (!user) {
      gatedActionRef.current = () => fn(...args)
      setAuthGateOpen(true)
      return
    }
    fn(...args)
  }

  const ensureConversationId = async () => {
    if (conversationId) return conversationId
    const { data } = await api.createConversation()
    setConversationId(data.conversation_id)
    return data.conversation_id
  }

  // A "busy right now" failure (LLM_RATE_LIMITED — every configured Groq key
  // momentarily out of quota, see nlp/ai_assistant.py) usually clears within
  // a few seconds, unlike every other failure here — see the identical
  // comment in Dashboard.jsx/ProjectChat.jsx. `id` is a plain parameter here
  // (not re-read from `conversationId` state), so the retry can never race
  // ensureConversationId() into creating a second, duplicate conversation.
  const sendToConversation = async (id, text, isAutoRetry = false) => {
    try {
      const { data } = await api.sendConversationMessage(id, text)
      return data
    } catch (err) {
      if (err.serverCode === 'LLM_RATE_LIMITED' && !isAutoRetry) {
        await new Promise((resolve) => setTimeout(resolve, 4000))
        return sendToConversation(id, text, true)
      }
      throw err
    }
  }

  // One conversation for the whole session — every generate/refine/roadmap/
  // follow-up call goes through it, which is what lets the model resolve
  // "the third one" later purely from the stored blocks (see the module
  // docstring above); this page never tracks idea context itself.
  const sendMessage = async (text) => {
    const id = await ensureConversationId()
    return sendToConversation(id, text)
  }

  const extractIdeasBlock = (blocks) => blocks?.find((b) => b.type === 'generated_project_ideas') ?? null

  // A fresh batch (many ideas) replaces the grid; a refinement (exactly one
  // idea back) patches just that card in place — "only refine the selected
  // idea," never the whole list.
  const mergeIdea = (block) => {
    if (!block?.ideas?.length) return
    if (block.ideas.length > 1) {
      setIdeas(block.ideas)
      return
    }
    const [updated] = block.ideas
    setIdeas((prev) => {
      const idx = prev.findIndex((i) => i.id === updated.id || i.name === updated.name)
      if (idx === -1) return [...prev, updated]
      const next = [...prev]
      next[idx] = updated
      return next
    })
  }

  const generate = async (overrideTopic) => {
    setStatus('loading')
    setError(null)
    const topicText = (overrideTopic ?? topic).trim()
    try {
      const parts = [
        `Generate ${count} new, original project idea${count === 1 ? '' : 's'} I could build` +
          `${ideas.length ? ', different from the ones already shown above' : ''}.`,
      ]
      if (topicText) parts.push(`Context: ${topicText}`)
      if (domain) parts.push(`Domain: ${domain}.`)
      if (difficulty) parts.push(`Difficulty: ${difficulty}.`)
      const data = await sendMessage(parts.join(' '))
      const block = extractIdeasBlock(data.blocks)
      if (!block?.ideas?.length) {
        setStatus('error')
        setError(data.reply || 'No ideas came back — try describing your project differently.')
        return
      }
      setIdeas(block.ideas)
      setSelectedIdeaId(null)
      setCompareIds(new Set())
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  const runStarter = withAuth((text) => {
    setTopic(text)
    generate(text)
  })

  const openRefine = (idea) => {
    setRefineTarget(idea)
    setRefineOptionKey(null)
    setRefineInput('')
    setRefineError(null)
  }

  const submitRefine = async () => {
    const option = REFINE_OPTIONS.find((o) => o.key === refineOptionKey)
    if (!option) {
      setRefineError('Choose how you want this idea improved.')
      return
    }
    if (option.needsInput && !refineInput.trim()) {
      setRefineError('Add a bit more detail first.')
      return
    }
    setRefineBusy(true)
    setRefineError(null)
    try {
      const instruction = option.instruction(refineTarget.name, refineInput.trim())
      const data = await sendMessage(instruction)
      const block = extractIdeasBlock(data.blocks)
      if (block) mergeIdea(block)
      setRefineTarget(null)
    } catch (err) {
      setRefineError(err.message)
    } finally {
      setRefineBusy(false)
    }
  }

  // Independent of the conversation — POST /api/uniqueness is the same
  // deterministic, model-free engine ideation._validate already ran once at
  // generation time, just re-run live so a re-check (after a refinement) or
  // the bonus "getting started" phase plan doesn't need Groq at all.
  const openUniqueness = async (idea) => {
    setUniquenessTarget(idea)
    setUniquenessStatus('loading')
    setUniquenessResult(null)
    setUniquenessError(null)
    try {
      const description = `${idea.problem} ${idea.solution}`.trim()
      const { data } = await api.uniqueness(idea.name, description, idea.domain, idea.technologies || [])
      setUniquenessResult(data)
      setUniquenessStatus('done')
    } catch (err) {
      setUniquenessError(err.message)
      setUniquenessStatus('error')
    }
  }

  const openRoadmap = async (idea) => {
    setRoadmapTarget(idea)
    setRoadmapStatus('loading')
    setRoadmapText('')
    try {
      const data = await sendMessage(`Create a roadmap for "${idea.name}".`)
      setRoadmapText(data.reply || 'No roadmap came back — try again.')
      setRoadmapStatus('done')
    } catch (err) {
      setRoadmapStatus('error')
      setRoadmapText(err.message)
    }
  }

  const toggleCompare = (id) => {
    setCompareIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else if (next.size < 4) next.add(id)
      return next
    })
  }

  // The real select_idea tool (nlp/chat_tools.py) — the idea-context mirror
  // of select_project, mutually exclusive with it on the conversation. One
  // natural-language message is enough for the model to call it with this
  // idea's exact fields (it already has them from the shown-ideas context),
  // exactly like the [Build This] chip in Dashboard.jsx's own IDEA_ACTIONS —
  // no separate "select" endpoint invented for this page.
  const selectIdea = async (idea) => {
    setSelectingId(idea.id)
    setSelectError(null)
    try {
      const data = await sendMessage(`Let's build "${idea.name}".`)
      setSelectedIdeaId(data.selected_idea?.id || idea.id)
    } catch (err) {
      setSelectError(err.message)
    } finally {
      setSelectingId(null)
    }
  }

  // Hands off into the existing AI Mentor thread (Dashboard.jsx) on the same
  // conversation_id — since selectIdea already set this idea as the
  // conversation's server-side selected_idea, Dashboard picks it up the
  // moment it loads (ActiveIdeaBanner + IDEA_BUILD_ACTIONS), no autosend
  // trick needed.
  const continueInMentor = () => {
    if (!conversationId) return
    navigate(`/dashboard?c=${conversationId}`)
  }

  const submitFollowUp = async () => {
    const text = followUpText.trim()
    if (!text || followUpBusy) return
    setFollowUpText('')
    setFollowUpBusy(true)
    setFollowUpThread((t) => [...t, { role: 'user', content: text }])
    try {
      const data = await sendMessage(text)
      setFollowUpThread((t) => [...t, { role: 'assistant', content: data.reply }])
      const block = extractIdeasBlock(data.blocks)
      if (block) mergeIdea(block)
    } catch (err) {
      setFollowUpThread((t) => [...t, { role: 'assistant', content: `Could not reach the assistant: ${err.message}` }])
    } finally {
      setFollowUpBusy(false)
    }
  }

  const selectedIdea = ideas.find((i) => i.id === selectedIdeaId) || null
  const compareIdeas = ideas.filter((i) => compareIds.has(i.id))
  const activeRefineOption = REFINE_OPTIONS.find((o) => o.key === refineOptionKey)

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        eyebrow="AI Ideation Engine"
        title="Invent your next project"
        description={
          'Describe what you want to build — ProjectMind’s AI will think up original project concepts, ' +
          'check each one against the catalogue, and help you turn one into a plan.'
        }
      />

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <Panel icon="auto_awesome" title="Describe what you want to build" compact>
            <div className="space-y-4">
              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  What are you building?
                </label>
                <textarea
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  rows={4}
                  placeholder='e.g. "An innovative NLP project I can finish in 3 months"'
                  className="gm-input w-full px-3 py-2 text-sm"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                    Domain
                  </label>
                  <select value={domain} onChange={(e) => setDomain(e.target.value)} className="gm-input w-full px-2 py-2 text-sm">
                    <option value="">Any</option>
                    {domains.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                    Difficulty
                  </label>
                  <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className="gm-input w-full px-2 py-2 text-sm">
                    <option value="">Any</option>
                    {difficulties.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  How many ideas?
                </label>
                <select value={count} onChange={(e) => setCount(Number(e.target.value))} className="gm-input w-full px-2 py-2 text-sm">
                  {Array.from({ length: IDEA_COUNT_MAX }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={withAuth(() => generate())}
                disabled={status === 'loading'}
                className="btn-primary t-label-caps w-full px-4 py-2"
              >
                {status === 'loading' ? 'Thinking…' : ideas.length > 0 ? 'Generate more ideas' : 'Generate ideas'}
              </button>

              {status === 'error' && error && (
                <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>
              )}

              <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
                Every idea is generated as a structured, consistent concept, then validated for originality against
                the catalogue — anything too close to an existing project is automatically strengthened before you
                ever see it.
              </p>
            </div>
          </Panel>

          {status === 'idle' && ideas.length === 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {STARTER_TOPICS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => runStarter(t)}
                  className="t-label-mono px-3 py-1.5 text-left transition hover:opacity-80"
                  style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 999 }}
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </aside>

        <section>
          {status === 'idle' && ideas.length === 0 && (
            <EmptyState
              title="Describe an idea to get started"
              hint="Fill in the panel on the left, then generate — ProjectMind will invent, validate, and originality-check a set of project concepts for you."
            />
          )}
          {status === 'loading' && ideas.length === 0 && <Spinner label="Thinking up original project concepts…" />}
          {status === 'error' && ideas.length === 0 && <ErrorNotice message={error} onRetry={() => generate()} />}

          {ideas.length > 0 && (
            <>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <p className="t-label-mono" style={{ color: 'var(--outline)' }}>
                  {ideas.length} AI-generated idea{ideas.length === 1 ? '' : 's'}
                </p>
                {status === 'loading' && (
                  <span className="t-label-mono" style={{ color: 'var(--outline)' }}>Generating more…</span>
                )}
              </div>

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {ideas.map((idea) => (
                  <GeneratedIdeaCard
                    key={idea.id}
                    idea={idea}
                    selected={idea.id === selectedIdeaId}
                    actions={[
                      { key: 'improve', label: 'Improve Idea', onClick: () => openRefine(idea) },
                      { key: 'uniqueness', label: 'Check Uniqueness', onClick: () => openUniqueness(idea) },
                      {
                        key: 'compare',
                        label: compareIds.has(idea.id) ? 'Remove Compare' : 'Compare',
                        active: compareIds.has(idea.id),
                        onClick: () => toggleCompare(idea.id),
                      },
                      { key: 'roadmap', label: 'Create Roadmap', onClick: () => openRoadmap(idea) },
                      {
                        key: 'select',
                        label: idea.id === selectedIdeaId ? 'Selected' : selectingId === idea.id ? 'Selecting…' : 'Select',
                        primary: idea.id === selectedIdeaId,
                        disabled: selectingId === idea.id,
                        onClick: () => selectIdea(idea),
                      },
                    ]}
                  />
                ))}
              </div>

              {selectError && (
                <p className="t-body-md mt-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{selectError}</p>
              )}

              {selectedIdea && (
                <div
                  className="glass-panel mt-6 flex flex-wrap items-center justify-between gap-4 p-4"
                  style={{ borderRadius: 8, border: '1px solid var(--primary)' }}
                >
                  <div className="min-w-0">
                    <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Working on</span>
                    <p className="t-label-mono truncate" style={{ color: 'var(--primary)', fontSize: 14 }}>{selectedIdea.name}</p>
                    <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
                      {selectedIdea.difficulty} · {selectedIdea.domain} · ~{selectedIdea.duration_weeks} weeks
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => openRoadmap(selectedIdea)}
                      className="btn-secondary t-label-caps px-3 py-1.5"
                      style={{ fontSize: 10.5 }}
                    >
                      Create Roadmap
                    </button>
                    <button
                      type="button"
                      onClick={continueInMentor}
                      className="btn-primary t-label-caps px-3 py-1.5"
                      style={{ fontSize: 10.5 }}
                    >
                      Continue in AI Mentor →
                    </button>
                  </div>
                </div>
              )}

              <div className="glass-panel mt-6 p-4" style={{ borderRadius: 8 }}>
                <p className="t-label-caps mb-2" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Ask about these ideas
                </p>
                {followUpThread.length > 0 && (
                  <div className="mb-3 max-h-64 space-y-3 overflow-y-auto pr-1">
                    {followUpThread.map((m, i) => (
                      <div key={i}>
                        <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9 }}>
                          {m.role === 'user' ? 'You' : 'Assistant'}
                        </span>
                        <div className="t-body-md mt-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
                          {m.role === 'user' ? m.content : <MarkdownLite content={m.content} />}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    withAuth(submitFollowUp)()
                  }}
                  className="flex gap-2"
                >
                  <input
                    value={followUpText}
                    onChange={(e) => setFollowUpText(e.target.value)}
                    placeholder='e.g. "Make the third one more innovative" or "Can I build it in 3 months?"'
                    className="gm-input flex-1 px-3 py-2 text-sm"
                  />
                  <button type="submit" disabled={followUpBusy || !followUpText.trim()} className="btn-primary t-label-caps px-4 py-2">
                    {followUpBusy ? '…' : 'Ask'}
                  </button>
                </form>
                <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
                  Context carries across the whole session — refer to ideas by name or position ("the third one") and follow-ups stay grounded in whichever one you mean.
                </p>
              </div>
            </>
          )}
        </section>
      </div>

      {compareIds.size > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-5">
          <div className="glass-panel flex items-center gap-4 px-4 py-3" style={{ borderRadius: 999 }}>
            <span className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>
              {compareIds.size} idea{compareIds.size === 1 ? '' : 's'} selected to compare
            </span>
            <button
              type="button"
              disabled={compareIds.size < 2}
              onClick={() => setShowCompare(true)}
              className="btn-primary t-label-caps px-3 py-1.5"
              style={{ fontSize: 10.5 }}
            >
              Compare
            </button>
            <button
              type="button"
              onClick={() => setCompareIds(new Set())}
              className="t-label-mono transition hover:opacity-70"
              style={{ color: 'var(--outline)', fontSize: 12 }}
            >
              Clear
            </button>
          </div>
        </div>
      )}

      <Modal
        open={Boolean(refineTarget)}
        onClose={() => setRefineTarget(null)}
        eyebrow="Improve Idea"
        title={refineTarget ? `How should we improve "${refineTarget.name}"?` : ''}
      >
        {refineTarget && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              {REFINE_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  type="button"
                  onClick={() => setRefineOptionKey(o.key)}
                  className="t-label-caps px-3 py-2.5 text-left transition hover:opacity-85"
                  style={{
                    border: `1px solid ${refineOptionKey === o.key ? 'var(--primary)' : 'var(--border-technical)'}`,
                    color: refineOptionKey === o.key ? 'var(--primary)' : 'var(--on-surface-variant)',
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                >
                  {o.label}
                </button>
              ))}
            </div>

            {activeRefineOption?.needsInput && (
              <input
                value={refineInput}
                onChange={(e) => setRefineInput(e.target.value)}
                placeholder={activeRefineOption.placeholder}
                autoFocus
                className="gm-input w-full px-3 py-2 text-sm"
              />
            )}

            {refineError && <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>{refineError}</p>}

            <button
              type="button"
              onClick={submitRefine}
              disabled={refineBusy || !refineOptionKey}
              className="btn-primary t-label-caps w-full px-4 py-2"
            >
              {refineBusy ? 'Refining…' : 'Refine this idea'}
            </button>
            <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
              Only this idea changes — the rest of your list stays exactly as it is.
            </p>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(uniquenessTarget)}
        onClose={() => setUniquenessTarget(null)}
        eyebrow="Check Uniqueness"
        title={uniquenessTarget?.name}
        maxWidth={640}
      >
        {uniquenessStatus === 'loading' && <Spinner label="Comparing against the catalogue…" />}
        {uniquenessStatus === 'error' && (
          <ErrorNotice message={uniquenessError} onRetry={() => openUniqueness(uniquenessTarget)} />
        )}
        {uniquenessStatus === 'done' && uniquenessResult && <UniquenessResult result={uniquenessResult} />}
      </Modal>

      <Modal
        open={Boolean(roadmapTarget)}
        onClose={() => setRoadmapTarget(null)}
        eyebrow="Roadmap"
        title={roadmapTarget ? `Roadmap for "${roadmapTarget.name}"` : ''}
        maxWidth={640}
      >
        {roadmapStatus === 'loading' && <Spinner label="Building a phase-by-phase plan…" />}
        {roadmapStatus === 'error' && <ErrorNotice message={roadmapText} onRetry={() => openRoadmap(roadmapTarget)} />}
        {roadmapStatus === 'done' && (
          <>
            <MarkdownLite content={roadmapText} />
            <button
              type="button"
              onClick={async () => {
                const idea = roadmapTarget
                setRoadmapTarget(null)
                if (idea.id !== selectedIdeaId) await selectIdea(idea)
                continueInMentor()
              }}
              className="btn-primary t-label-caps mt-5 px-4 py-2"
            >
              Continue in AI Mentor →
            </button>
          </>
        )}
      </Modal>

      <Modal open={showCompare} onClose={() => setShowCompare(false)} eyebrow="Compare" title="Comparing generated ideas" maxWidth={820}>
        <div className="overflow-x-auto">
          <table className="w-full text-left" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th className="pb-2 pr-4" />
                {compareIdeas.map((i) => (
                  <th key={i.id} className="t-label-mono pb-2 pr-4 align-top" style={{ color: 'var(--primary)', fontSize: 13 }}>
                    {i.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARE_ROWS.map((row) => (
                <tr key={row.label} style={{ borderTop: '1px solid var(--border-technical)' }}>
                  <td className="t-label-caps py-2 pr-4 align-top" style={{ color: 'var(--outline)', fontSize: 10, whiteSpace: 'nowrap' }}>
                    {row.label}
                  </td>
                  {compareIdeas.map((i) => (
                    <td key={i.id} className="t-body-md py-2 pr-4 align-top" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                      {row.get(i) || '—'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Modal>

      <AuthGateModal
        open={authGateOpen}
        onClose={() => {
          setAuthGateOpen(false)
          gatedActionRef.current = null
        }}
        onAuthenticated={() => {
          setAuthGateOpen(false)
          const fn = gatedActionRef.current
          gatedActionRef.current = null
          if (fn) fn()
        }}
        message="Sign in to generate and refine AI project ideas — your request will run right after."
      />
    </div>
  )
}
