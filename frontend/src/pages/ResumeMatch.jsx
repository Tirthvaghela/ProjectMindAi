import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

const ACCEPTED = '.pdf,.docx,.txt'

/** Same have/missing layout as Dashboard's SkillGapBlock (backend/nlp/recommend.py:skill_gap),
 * just for the résumé-match card instead of a chat turn. */
function SkillPills({ have, missing }) {
  if (!have?.length && !missing?.length) return null
  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      <div>
        <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>You have</p>
        <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          {have?.length ? have.map((s) => <li key={s}>✓ {s}</li>) : <li style={{ color: 'var(--outline)' }}>None yet</li>}
        </ul>
      </div>
      <div>
        <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Missing</p>
        <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          {missing?.length ? missing.map((s) => <li key={s}>✗ {s}</li>) : <li style={{ color: 'var(--outline)' }}>None</li>}
        </ul>
      </div>
    </div>
  )
}

/**
 * Wraps the existing ProjectCard unchanged (it already renders match %, why
 * it matched, technologies, difficulty, duration, favourite, GitHub link,
 * and the click-through to Project Detail) and adds only what résumé
 * matching needs on top: the skill checklist, and Select/Compare actions
 * that hand off into the same selected-project workflow the chat's own
 * [Select Project] button uses — not a second selection mechanism.
 */
function ResumeMatchCard({ project, isFavorite, onToggleFavorite, index, busyKind, onSelect, onCompare }) {
  return (
    <div className="flex flex-col">
      <ProjectCard project={project} isFavorite={isFavorite} onToggleFavorite={onToggleFavorite} index={index} />
      <div className="glass-panel -mt-2 p-4" style={{ borderRadius: 8 }}>
        <SkillPills have={project.skills_you_have} missing={project.skills_to_learn} />
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            to={`/project/${project.project_id}`}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            View Project
          </Link>
          <button
            type="button"
            onClick={() => onSelect(project)}
            disabled={Boolean(busyKind)}
            className="btn-primary t-label-caps px-3 py-1.5 disabled:opacity-60"
            style={{ fontSize: 10.5 }}
          >
            {busyKind === 'select' ? 'Selecting…' : 'Select Project'}
          </button>
          <button
            type="button"
            onClick={() => onCompare(project)}
            disabled={Boolean(busyKind)}
            className="t-label-caps px-3 py-1.5 transition hover:opacity-80 disabled:opacity-60"
            style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 6, fontSize: 10.5 }}
          >
            {busyKind === 'compare' ? 'Opening…' : 'Compare'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ResumeMatch() {
  const navigate = useNavigate()
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [actionBusy, setActionBusy] = useState(null) // { projectId, kind } | null
  const [actionError, setActionError] = useState(null)
  const [chatBusy, setChatBusy] = useState(false)
  const { isFavorite, toggle } = useFavorites()

  // Both [Select Project] and [Compare] start the same way: a fresh
  // conversation, the project selected into it via the exact endpoint the
  // chat's own Select Project button calls, then a handoff to the Dashboard,
  // which already knows how to show the active-project banner and (for
  // Compare) auto-send the same prompt its own action chip sends. Also
  // attaches the résumé's already-detected skills (see api.attachResumeSkills)
  // so the conversation carries résumé context from the start — a follow-up
  // like "what should I learn for this?" doesn't need the résumé re-uploaded.
  const startWorkflow = async (project, kind) => {
    setActionBusy({ projectId: project.project_id, kind })
    setActionError(null)
    try {
      const { data } = await api.createConversation()
      const tasks = [api.selectProject(data.conversation_id, project.project_id)]
      if (result?.detected_skills?.length > 0) {
        tasks.push(api.attachResumeSkills(data.conversation_id, result.detected_skills))
      }
      await Promise.all(tasks)
      const params = new URLSearchParams({ c: data.conversation_id })
      if (kind === 'compare') params.set('autosend', 'Compare')
      navigate(`/dashboard?${params.toString()}`)
    } catch (err) {
      setActionError(err.message)
      setActionBusy(null)
    }
  }

  // A fresh conversation with the résumé's detected skills attached but no
  // project pre-selected — for "which project fits me best?" before the
  // student has picked one. Dashboard's autosend mechanism sends this text
  // verbatim as the first message once the résumé context is attached
  // (see Dashboard.jsx's autosend effect — same hand-off Ideate's "Continue
  // in AI Mentor" uses for a free-form question rather than a canned action).
  const discussInChat = async () => {
    setChatBusy(true)
    setActionError(null)
    try {
      const { data } = await api.createConversation()
      if (result?.detected_skills?.length > 0) {
        await api.attachResumeSkills(data.conversation_id, result.detected_skills)
      }
      const params = new URLSearchParams({
        c: data.conversation_id,
        autosend: 'Which project fits me best based on my résumé?',
      })
      navigate(`/dashboard?${params.toString()}`)
    } catch (err) {
      setActionError(err.message)
      setChatBusy(false)
    }
  }

  const submit = async () => {
    if (!file && !text.trim()) {
      setError('Upload a résumé file, or paste your résumé text below.')
      return
    }
    setStatus('loading')
    setError(null)
    try {
      const response = await api.resumeSuggest({ file, text })
      setResult(response)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        title="Match projects to your résumé"
        description="Upload your résumé — or paste it in — and we'll find projects that fit the skills and experience you already have."
      />

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <Panel icon="upload_file" title="Add your résumé" compact>
            <div className="space-y-4">
              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Résumé file (PDF, DOCX or TXT)
                </label>
                <input
                  type="file"
                  accept={ACCEPTED}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-sm file:mr-3 file:border-0 file:px-3 file:py-2 file:text-sm file:font-medium"
                  style={{ color: 'var(--on-surface-variant)' }}
                />
                {file && (
                  <p className="t-body-md mt-1.5 flex items-center gap-1.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                    {file.name}
                    <button onClick={() => setFile(null)} style={{ color: 'var(--outline)' }} className="transition hover:opacity-70">
                      ✕
                    </button>
                  </p>
                )}
              </div>

              <div className="t-label-mono flex items-center gap-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
                <span className="h-px flex-1" style={{ background: 'var(--border-technical)' }} />
                or
                <span className="h-px flex-1" style={{ background: 'var(--border-technical)' }} />
              </div>

              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Paste your résumé text
                </label>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={8}
                  placeholder="Paste your experience, skills, past projects…"
                  className="gm-input w-full px-3 py-2 text-sm"
                />
              </div>

              <button
                onClick={submit}
                disabled={status === 'loading'}
                className="btn-primary t-label-caps w-full px-4 py-2"
              >
                {status === 'loading' ? 'Reading…' : 'Find matching projects'}
              </button>

              {error && <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

              <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
                Your résumé file itself is read once to find matches, then discarded. If you continue
                into AI chat, only the skills shown below (never the résumé file or text) are attached
                to that conversation.
              </p>
            </div>
          </Panel>
        </aside>

        <section>
          {status === 'idle' && (
            <EmptyState
              title="Add your résumé to get started"
              hint="Upload a file or paste your text on the left, then find matching projects."
            />
          )}
          {status === 'loading' && <Spinner label="Matching your résumé against the catalogue…" />}
          {status === 'error' && <ErrorNotice message={error} onRetry={submit} />}

          {status === 'done' && result && (
            <>
              {result.detected_skills.length > 0 && (
                <div className="glass-panel mb-5 p-4" style={{ borderRadius: 8 }}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
                      Skills we found on your résumé
                    </p>
                    <button
                      type="button"
                      onClick={discussInChat}
                      disabled={chatBusy}
                      className="t-label-caps shrink-0 px-2.5 py-1 transition hover:opacity-80 disabled:opacity-60"
                      style={{ border: '1px solid var(--primary)', color: 'var(--primary)', borderRadius: 999, fontSize: 10 }}
                    >
                      {chatBusy ? 'Opening…' : 'Ask the AI Assistant'}
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {result.detected_skills.map((skill) => (
                      <span
                        key={skill}
                        className="gm-chip px-2 py-1"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {actionError && (
                <p className="t-body-md mb-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{actionError}</p>
              )}

              {result.data.length === 0 ? (
                <EmptyState
                  title="No strong matches"
                  hint="Try pasting more of your experience, or browse the full catalogue instead."
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  {result.data.map((project, index) => (
                    <ResumeMatchCard
                      key={project.project_id}
                      project={project}
                      index={index}
                      isFavorite={isFavorite(project.project_id)}
                      onToggleFavorite={toggle}
                      busyKind={actionBusy?.projectId === project.project_id ? actionBusy.kind : null}
                      onSelect={(p) => startWorkflow(p, 'select')}
                      onCompare={(p) => startWorkflow(p, 'compare')}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
