import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import useProfile, { announceProfileChanged } from '../hooks/useProfile'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

// Setup walks through these one at a time; the same sections are all shown
// together when editing later. `fields` are the API sections each step saves.
const STEPS = [
  { key: 'skills', title: 'Skills', fields: ['skills'] },
  { key: 'interests', title: 'Interests', fields: ['interests'] },
  { key: 'goals', title: 'Goals & roles', fields: ['learning_goals', 'career_interests', 'preferred_roles'] },
  { key: 'time', title: 'Time & background', fields: ['availability', 'experience', 'education'] },
]

const inputStyle = { color: 'var(--on-surface)' }
const mutedStyle = { color: 'var(--on-surface-variant)' }

function Section({ title, hint, children, id }) {
  return (
    <section className="glass-panel p-5 sm:p-6" style={{ borderRadius: 8 }} aria-labelledby={id}>
      <h2 id={id} className="t-headline-md" style={{ color: 'var(--primary)', fontSize: 16 }}>
        {title}
      </h2>
      {hint && (
        <p className="t-body-md mt-1" style={{ ...mutedStyle, fontSize: 13 }}>
          {hint}
        </p>
      )}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Chip({ children, onRemove, label }) {
  return (
    <span
      className="t-label-mono inline-flex items-center gap-1.5 px-2.5 py-1"
      style={{ border: '1px solid var(--border-technical)', borderRadius: 999, fontSize: 12, color: 'var(--on-surface)' }}
    >
      {children}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={label} className="grid place-items-center opacity-70 hover:opacity-100">
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
            close
          </span>
        </button>
      )}
    </span>
  )
}

function SkillsEditor({ skills, levels, max, onChange }) {
  const [name, setName] = useState('')
  const [level, setLevel] = useState(levels[0])

  const add = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    // The server merges aliases ("reactjs" = "React"); this only avoids an
    // obviously doubled row appearing before the next save.
    const exists = skills.some((s) => s.name.toLowerCase() === trimmed.toLowerCase())
    const next = exists
      ? skills.map((s) => (s.name.toLowerCase() === trimmed.toLowerCase() ? { ...s, level } : s))
      : [...skills, { name: trimmed, level }]
    onChange(next)
    setName('')
  }

  return (
    <div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[10rem] flex-1">
          <span className="t-label-caps block" style={{ ...mutedStyle, fontSize: 10 }}>
            Skill or technology
          </span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                add()
              }
            }}
            maxLength={60}
            placeholder="e.g. React, Python, SQL"
            className="gm-input mt-1 w-full px-3 py-2 text-sm"
            style={inputStyle}
          />
        </label>
        <label>
          <span className="t-label-caps block" style={{ ...mutedStyle, fontSize: 10 }}>
            Level
          </span>
          <select value={level} onChange={(e) => setLevel(e.target.value)} className="gm-input mt-1 px-3 py-2 text-sm" style={inputStyle}>
            {levels.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={add}
          disabled={!name.trim() || skills.length >= max}
          className="t-label-caps px-4 py-2.5 transition hover:opacity-85 disabled:opacity-40"
          style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
        >
          Add skill
        </button>
      </div>
      <p className="t-body-md mt-2" style={{ ...mutedStyle, fontSize: 12 }}>
        Levels are your own estimate — they are never treated as verified.
      </p>

      {skills.length === 0 ? (
        <p className="t-body-md mt-4" style={mutedStyle}>
          No skills yet. Add a few — you can always change them later.
        </p>
      ) : (
        <ul className="mt-4 space-y-2" aria-label="Your skills">
          {skills.map((skill) => (
            <li key={skill.name} className="flex flex-wrap items-center justify-between gap-2" style={{ borderBottom: '1px solid var(--border-technical)', paddingBottom: 8 }}>
              <span className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
                {skill.name}
                {skill.recognised === false && (
                  <span title="Not in the project catalogue's skill list, so it won't match projects automatically" style={{ ...mutedStyle, fontSize: 11 }}>
                    {' '}
                    · custom
                  </span>
                )}
              </span>
              <span className="flex items-center gap-2">
                <select
                  aria-label={`Level for ${skill.name}`}
                  value={skill.level}
                  onChange={(e) => onChange(skills.map((s) => (s.name === skill.name ? { ...s, level: e.target.value } : s)))}
                  className="gm-input px-2 py-1 text-xs"
                  style={inputStyle}
                >
                  {levels.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </select>
                <button
                  type="button"
                  aria-label={`Remove ${skill.name}`}
                  onClick={() => onChange(skills.filter((s) => s.name !== skill.name))}
                  className="grid h-7 w-7 place-items-center opacity-70 hover:opacity-100"
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                    delete
                  </span>
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ChoiceChips({ options, selected, onChange, label }) {
  const toggle = (option) => onChange(selected.includes(option) ? selected.filter((o) => o !== option) : [...selected, option])
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((option) => {
        const on = selected.includes(option)
        return (
          <button
            key={option}
            type="button"
            aria-pressed={on}
            onClick={() => toggle(option)}
            className="t-label-mono px-3 py-1.5 transition hover:opacity-85"
            style={{
              fontSize: 12,
              borderRadius: 999,
              border: `1px solid ${on ? 'var(--primary)' : 'var(--border-technical)'}`,
              background: on ? 'var(--primary)' : 'transparent',
              color: on ? 'var(--on-primary)' : 'var(--on-surface-variant)',
            }}
          >
            {option}
          </button>
        )
      })}
    </div>
  )
}

function TagList({ items, onChange, label, placeholder, max, maxChars }) {
  const [text, setText] = useState('')
  const add = () => {
    const value = text.trim()
    if (!value || items.some((i) => i.toLowerCase() === value.toLowerCase()) || items.length >= max) return
    onChange([...items, value])
    setText('')
  }
  return (
    <div>
      <div className="flex gap-2">
        <input
          aria-label={label}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          maxLength={maxChars}
          placeholder={placeholder}
          className="gm-input min-w-0 flex-1 px-3 py-2 text-sm"
          style={inputStyle}
        />
        <button type="button" onClick={add} disabled={!text.trim()} className="t-label-caps px-3 py-2 transition hover:opacity-85 disabled:opacity-40" style={{ border: '1px solid var(--border-technical)', borderRadius: 8, color: 'var(--on-surface)' }}>
          Add
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {items.map((item) => (
          <Chip key={item} label={`Remove ${item}`} onRemove={() => onChange(items.filter((i) => i !== item))}>
            {item}
          </Chip>
        ))}
      </div>
    </div>
  )
}

function ExperienceEditor({ items, max, onChange }) {
  const update = (index, patch) => onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  return (
    <div>
      <ul className="space-y-4">
        {items.map((item, index) => (
          <li key={index} className="space-y-2 p-3" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
            <input
              aria-label={`Project ${index + 1} title`}
              value={item.title}
              onChange={(e) => update(index, { title: e.target.value })}
              maxLength={100}
              placeholder="Project or experience title"
              className="gm-input w-full px-3 py-2 text-sm"
              style={inputStyle}
            />
            <textarea
              aria-label={`Project ${index + 1} description`}
              value={item.description}
              onChange={(e) => update(index, { description: e.target.value })}
              maxLength={500}
              rows={2}
              placeholder="What did you build or do? (optional)"
              className="gm-input w-full px-3 py-2 text-sm"
              style={inputStyle}
            />
            <input
              aria-label={`Project ${index + 1} technologies`}
              value={(item.technologies || []).join(', ')}
              onChange={(e) => update(index, { technologies: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })}
              placeholder="Technologies, comma separated"
              className="gm-input w-full px-3 py-2 text-sm"
              style={inputStyle}
            />
            <button type="button" onClick={() => onChange(items.filter((_, i) => i !== index))} className="t-label-caps" style={{ color: '#ffb4ab', fontSize: 11 }}>
              Remove entry
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => onChange([...items, { title: '', description: '', technologies: [] }])}
        disabled={items.length >= max}
        className="t-label-caps mt-3 px-3 py-2 transition hover:opacity-85 disabled:opacity-40"
        style={{ border: '1px solid var(--border-technical)', borderRadius: 8, color: 'var(--on-surface)' }}
      >
        Add a past project
      </button>
    </div>
  )
}

function NumberField({ label, value, onChange, max, hint }) {
  return (
    <label className="block">
      <span className="t-label-caps block" style={{ ...mutedStyle, fontSize: 10 }}>
        {label}
      </span>
      <input
        type="number"
        min={1}
        max={max}
        inputMode="numeric"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className="gm-input mt-1 w-full px-3 py-2 text-sm"
        style={inputStyle}
      />
      {hint && (
        <span className="t-body-md mt-1 block" style={{ ...mutedStyle, fontSize: 12 }}>
          {hint}
        </span>
      )}
    </label>
  )
}

function CompletionMeter({ completion }) {
  const labels = { not_started: 'Not started', in_progress: 'In progress', complete: 'Complete' }
  return (
    <div className="glass-panel mb-6 p-4" style={{ borderRadius: 8 }}>
      <div className="flex items-center justify-between gap-3">
        <span className="t-label-caps" style={{ color: 'var(--on-surface)', fontSize: 11 }}>
          Profile · {labels[completion.status]}
        </span>
        <span className="t-label-mono" style={{ color: 'var(--primary)' }}>
          {completion.percent}%
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden" style={{ background: 'var(--surface-container-high)', borderRadius: 999 }} role="progressbar" aria-valuenow={completion.percent} aria-valuemin={0} aria-valuemax={100} aria-label="Profile completion">
        <div className="h-full" style={{ width: `${completion.percent}%`, background: 'var(--primary)' }} />
      </div>
      {completion.missing.length > 0 && (
        <p className="t-body-md mt-2" style={{ ...mutedStyle, fontSize: 12 }}>
          Still to add: {completion.missing.map((m) => m.label.toLowerCase() + (m.core ? '' : ' (optional)')).join(', ')}.
        </p>
      )}
    </div>
  )
}

function toDraft(profile) {
  return {
    skills: profile.skills.map(({ name, level, recognised }) => ({ name, level, recognised })),
    interests: [...profile.interests],
    experience: profile.experience.map((e) => ({ ...e, technologies: [...(e.technologies || [])] })),
    learning_goals: [...profile.learning_goals],
    career_interests: [...profile.career_interests],
    preferred_roles: [...profile.preferred_roles],
    availability: { ...profile.availability },
    education: profile.education || '',
  }
}

// Only the API's own fields go back; `recognised` is derived server-side, and
// half-typed experience rows without a title would be rejected, so drop them.
function payloadFor(fields, draft) {
  const out = {}
  for (const field of fields) {
    if (field === 'skills') out.skills = draft.skills.map(({ name, level }) => ({ name, level }))
    else if (field === 'experience') out.experience = draft.experience.filter((e) => e.title.trim())
    else out[field] = draft[field]
  }
  return out
}

function SharingSection({ shared, onChanged }) {
  const [value, setValue] = useState(Boolean(shared))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => setValue(Boolean(shared)), [shared])

  const change = async (next) => {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const { data } = await api.saveLearnerProfile({ share_with_teams: next })
      setValue(Boolean(data.share_with_teams))
      setSaved(true)
      onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section id="sharing" title="Sharing with teammates" hint="Off by default. You can change this at any time.">
      <label className="flex items-start gap-3" style={{ color: 'var(--on-surface)' }}>
        <input
          type="checkbox"
          checked={value}
          disabled={busy}
          onChange={(e) => change(e.target.checked)}
          aria-describedby="sharing-help"
          className="mt-1"
        />
        <span className="t-body-md" style={{ fontSize: 14 }}>Let my teammates use my relevant skills for role suggestions and team formation</span>
      </label>
      <p id="sharing-help" className="t-body-md mt-2" style={{ ...mutedStyle, fontSize: 12.5 }}>
        When on, people on teams you belong to can see the skills and self-reported levels that matter for a role or a project, and a
        role suggestion for you. Your goals, education, hours and past-project descriptions are never shown. When off, those features stop
        using your profile from now on; skills you type in for a specific team are still used. Turning it off does not erase anything a
        teammate has already seen.
      </p>
      <div aria-live="polite" className="mt-2">
        {busy && <p className="t-label-mono" style={{ ...mutedStyle, fontSize: 12 }}>Saving…</p>}
        {error && <p role="alert" className="t-body-md" style={{ color: '#ffb4ab', fontSize: 12.5 }}>{error}</p>}
        {saved && !busy && !error && (
          <p className="t-label-mono" style={{ color: '#7bcf9f', fontSize: 12 }}>{value ? 'Sharing is on.' : 'Sharing is off.'}</p>
        )}
      </div>
    </Section>
  )
}

export default function Profile() {
  const { user, loading: authLoading } = useAuth()
  const { profile, status, error, reload } = useProfile()
  const [searchParams, setSearchParams] = useSearchParams()
  const [options, setOptions] = useState(null)
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [savedAt, setSavedAt] = useState(null)
  const [step, setStep] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const setupMode = searchParams.get('setup') === '1'

  useEffect(() => {
    api.learnerProfileOptions().then((res) => setOptions(res.data)).catch(() => setOptions(null))
  }, [])

  // Seed the editable draft once per load; later saves update it directly so a
  // background refetch never clobbers what the user is typing.
  useEffect(() => {
    if (profile && !draft) setDraft(toDraft(profile))
  }, [profile, draft])

  const visibleSections = useMemo(() => (setupMode ? [STEPS[step].key] : STEPS.map((s) => s.key)), [setupMode, step])

  if (authLoading || (user && (status === 'idle' || status === 'loading'))) return <Spinner label="Loading your profile…" />

  if (!user) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <EmptyState title="Sign in to build your profile" hint="Your skills and goals are saved to your account, so we need to know who you are first.">
          <Link to="/account" className="t-label-caps mt-4 inline-block px-4 py-2" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}>
            Sign in
          </Link>
        </EmptyState>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <ErrorNotice message={error} onRetry={reload} />
      </div>
    )
  }

  if (!draft || !options) return <Spinner label="Loading your profile…" />

  const patch = (changes) => {
    setDraft((d) => ({ ...d, ...changes }))
    setSavedAt(null)
  }

  const save = async (fields) => {
    setSaving(true)
    setSaveError(null)
    try {
      const { data } = await api.saveLearnerProfile(payloadFor(fields, draft))
      setDraft(toDraft(data))
      setSavedAt(new Date())
      announceProfileChanged()
      return true
    } catch (err) {
      setSaveError(err.message)
      return false
    } finally {
      setSaving(false)
    }
  }

  const finishSetup = () => setSearchParams({})

  const next = async () => {
    if (await save(STEPS[step].fields)) {
      if (step === STEPS.length - 1) finishSetup()
      else setStep(step + 1)
    }
  }

  const notNow = async () => {
    try {
      await api.saveLearnerProfile({ onboarding_dismissed: true })
      announceProfileChanged()
    } catch {
      /* Dismissal is a convenience; failing to store it must not trap the user here. */
    }
    finishSetup()
  }

  const remove = async () => {
    try {
      await api.deleteLearnerProfile()
      const { data } = await api.learnerProfile()
      setDraft(toDraft(data))
      setConfirmDelete(false)
      setSavedAt(null)
      announceProfileChanged()
    } catch (err) {
      setSaveError(err.message)
    }
  }

  const show = (key) => visibleSections.includes(key)
  const limits = options.limits

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow={setupMode ? `Setup · step ${step + 1} of ${STEPS.length}` : 'Your account'}
        title={setupMode ? STEPS[step].title : 'Your profile'}
        description="Used to tailor recommendations and team suggestions to you. Nothing here is shared with other users, and every section is optional."
      />

      <CompletionMeter completion={profile.completion} />

      <div className="space-y-5">
        {show('skills') && (
          <Section id="sec-skills" title="Skills" hint="Technologies and skills you already use, with an honest level.">
            <SkillsEditor skills={draft.skills} levels={options.proficiency_levels} max={limits.skills} onChange={(skills) => patch({ skills })} />
          </Section>
        )}

        {show('interests') && (
          <Section id="sec-interests" title="Project interests" hint="Domains you would enjoy building in.">
            <ChoiceChips label="Project interests" options={options.domains} selected={draft.interests} onChange={(interests) => patch({ interests })} />
          </Section>
        )}

        {show('goals') && (
          <>
            <Section id="sec-goals" title="Learning goals" hint="What do you want to get better at?">
              <TagList label="Learning goal" placeholder="e.g. Learn to deploy with Docker" items={draft.learning_goals} max={limits.goals} maxChars={limits.goal_chars} onChange={(learning_goals) => patch({ learning_goals })} />
            </Section>
            <Section id="sec-career" title="Career interests" hint="Roles or paths you are considering.">
              <TagList label="Career interest" placeholder="e.g. Data engineer" items={draft.career_interests} max={limits.career} maxChars={80} onChange={(career_interests) => patch({ career_interests })} />
            </Section>
            <Section id="sec-roles" title="Preferred team roles" hint="Roles you would like to take in a team. Suggestions stay advisory.">
              <ChoiceChips label="Preferred team roles" options={options.team_roles} selected={draft.preferred_roles} onChange={(preferred_roles) => patch({ preferred_roles })} />
            </Section>
          </>
        )}

        {show('time') && (
          <>
            <Section id="sec-time" title="Time available" hint="Helps us avoid suggesting projects you cannot finish.">
              <div className="grid gap-4 sm:grid-cols-2">
                <NumberField label="Hours per week" value={draft.availability.hours_per_week} max={limits.hours_per_week} onChange={(v) => patch({ availability: { ...draft.availability, hours_per_week: v } })} />
                <NumberField label="Longest project you want (weeks)" value={draft.availability.max_project_weeks} max={limits.max_project_weeks} onChange={(v) => patch({ availability: { ...draft.availability, max_project_weeks: v } })} />
              </div>
            </Section>
            <Section id="sec-exp" title="Past projects" hint="Optional. Short entries are enough.">
              <ExperienceEditor items={draft.experience} max={limits.experience} onChange={(experience) => patch({ experience })} />
            </Section>
            <Section id="sec-edu" title="Education" hint="Optional — only if it is useful to you.">
              <input
                aria-label="Education"
                value={draft.education}
                onChange={(e) => patch({ education: e.target.value })}
                maxLength={200}
                placeholder="e.g. BSc Computer Science, year 2"
                className="gm-input w-full px-3 py-2 text-sm"
                style={inputStyle}
              />
            </Section>
          </>
        )}
      </div>

      <div className="mt-6" aria-live="polite">
        {saveError && <ErrorNotice message={saveError} />}
        {savedAt && !saveError && (
          <p className="t-label-mono" style={{ color: '#7bcf9f' }}>
            Saved.
          </p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {setupMode ? (
          <>
            {step > 0 && (
              <button type="button" onClick={() => setStep(step - 1)} className="t-label-caps px-4 py-2.5" style={{ border: '1px solid var(--border-technical)', borderRadius: 8, color: 'var(--on-surface)' }}>
                Back
              </button>
            )}
            <button type="button" onClick={next} disabled={saving} className="t-label-caps px-5 py-2.5 transition hover:opacity-85 disabled:opacity-50" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}>
              {saving ? 'Saving…' : step === STEPS.length - 1 ? 'Save and finish' : 'Save and continue'}
            </button>
            {step < STEPS.length - 1 && (
              <button type="button" onClick={() => setStep(step + 1)} className="t-label-caps px-3 py-2.5" style={mutedStyle}>
                Skip this step
              </button>
            )}
            <button type="button" onClick={notNow} className="t-label-caps ml-auto px-3 py-2.5" style={mutedStyle}>
              Not now
            </button>
          </>
        ) : (
          <button type="button" onClick={() => save(STEPS.flatMap((s) => s.fields))} disabled={saving} className="t-label-caps px-5 py-2.5 transition hover:opacity-85 disabled:opacity-50" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}>
            {saving ? 'Saving…' : 'Save profile'}
          </button>
        )}
      </div>

      {!setupMode && (
        <div className="mt-8">
          <SharingSection shared={profile.share_with_teams} onChanged={announceProfileChanged} />
        </div>
      )}

      {!setupMode && (
        <div className="mt-12 pt-6" style={{ borderTop: '1px solid var(--border-technical)' }}>
          <h2 className="t-label-caps" style={{ color: 'var(--on-surface)', fontSize: 11 }}>
            Delete profile data
          </h2>
          <p className="t-body-md mt-1" style={{ ...mutedStyle, fontSize: 13 }}>
            Removes your saved skills, interests and goals. Your account, teams and favourites are not affected.
          </p>
          {confirmDelete ? (
            <div className="mt-3 flex gap-3">
              <button type="button" onClick={remove} className="t-label-caps px-4 py-2" style={{ background: '#ffb4ab', color: '#1a0000', borderRadius: 8 }}>
                Yes, delete profile
              </button>
              <button type="button" onClick={() => setConfirmDelete(false)} className="t-label-caps px-4 py-2" style={mutedStyle}>
                Cancel
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirmDelete(true)} className="t-label-caps mt-3 px-4 py-2" style={{ border: '1px solid rgba(255,180,171,0.4)', color: '#ffb4ab', borderRadius: 8 }}>
              Delete profile…
            </button>
          )}
        </div>
      )}
    </div>
  )
}
