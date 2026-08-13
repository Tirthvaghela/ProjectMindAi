import { useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import Panel from './Panel'

function emptyMember() {
  return { name: '', skillsText: '' }
}

function MemberRow({ index, member, onChange, onRemove, canRemove }) {
  return (
    <div className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
      <input
        value={member.name}
        onChange={(e) => onChange({ ...member, name: e.target.value })}
        placeholder={`Member ${index + 1} name (optional)`}
        className="gm-input w-full px-3 py-2 text-sm sm:w-44 sm:shrink-0"
      />
      <input
        value={member.skillsText}
        onChange={(e) => onChange({ ...member, skillsText: e.target.value })}
        placeholder="Their skills, comma separated — Python, React, testing…"
        className="gm-input w-full flex-1 px-3 py-2 text-sm"
      />
      <button
        type="button"
        onClick={onRemove}
        disabled={!canRemove}
        aria-label={`Remove member ${index + 1}`}
        className="shrink-0 self-end p-2 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-0 sm:self-auto"
        style={{ color: 'var(--outline)', borderRadius: 6 }}
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  )
}

function AssignmentCard({ assignment, index }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="p-4"
      style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>{assignment.member}</p>
        <span className="gm-chip px-2 py-0.5" style={{ borderColor: 'var(--outline)' }}>
          {assignment.category}
        </span>
      </div>
      <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)' }}>
        → <span style={{ color: 'var(--on-surface)' }}>{assignment.assigned_role}</span>
      </p>

      {assignment.fallback ? (
        <p className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 12 }}>
          No open role matched their strongest area{assignment.strongest_category ? ` (${assignment.strongest_category})` : ''}
          {' '}— filling this role to keep every seat covered.
        </p>
      ) : null}

      {assignment.matched_skills?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {assignment.matched_skills.map((skill) => (
            <span
              key={skill}
              className="t-label-mono px-1.5 py-0.5"
              style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 11, borderRadius: 4 }}
            >
              {skill}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  )
}

/**
 * Team role suggestion, on demand.
 *
 * Roles come from the same domain module breakdown the roadmap/synopsis
 * generator uses (nlp/generator.py), so the roles shown here line up with
 * what "Plan this project" already told the student the build looks like.
 */
export default function TeamBuilder({ projectId }) {
  const [members, setMembers] = useState([emptyMember(), emptyMember()])
  const [result, setResult] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const updateMember = (index, next) =>
    setMembers((current) => current.map((m, i) => (i === index ? next : m)))

  const addMember = () => {
    if (members.length >= 10) return
    setMembers((current) => [...current, emptyMember()])
  }

  const removeMember = (index) =>
    setMembers((current) => current.filter((_, i) => i !== index))

  const build = async () => {
    const payload = members
      .map((m) => ({
        name: m.name.trim(),
        skills: m.skillsText.split(',').map((s) => s.trim()).filter(Boolean),
      }))
      .filter((m) => m.name || m.skills.length)

    if (payload.length === 0) {
      setError('Add at least one teammate with a skill or two.')
      return
    }

    setStatus('loading')
    setError(null)
    try {
      const { data } = await api.teamBuilder(projectId, payload)
      setResult(data)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('idle')
    }
  }

  return (
    <Panel icon="assignment_ind" title="Team builder" description="List your teammates and what each is good at — we'll suggest who takes which part.">
      <div className="space-y-2">
        {members.map((member, index) => (
          <MemberRow
            key={index}
            index={index}
            member={member}
            onChange={(next) => updateMember(index, next)}
            onRemove={() => removeMember(index)}
            canRemove={members.length > 1}
          />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={addMember}
          disabled={members.length >= 10}
          className="t-label-caps px-3 py-1.5 transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-40"
          style={{ border: '1px dashed var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 8 }}
        >
          + Add teammate
        </button>
        <button
          type="button"
          onClick={build}
          disabled={status === 'loading'}
          className="btn-primary t-label-caps px-4 py-2"
        >
          {status === 'loading' ? 'Assigning roles…' : 'Suggest roles'}
        </button>
      </div>

      {error && <p className="t-body-md mt-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

      {result && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-5 space-y-3 pt-5" style={{ borderTop: '1px solid var(--border-technical)' }}>
          {result.assignments.map((assignment, i) => (
            <AssignmentCard key={assignment.member + i} assignment={assignment} index={i} />
          ))}

          {result.unfilled_roles?.length > 0 && (
            <p className="t-body-md p-3" style={{ background: 'var(--surface-container-low)', color: 'var(--on-surface-variant)', fontSize: 12.5, borderRadius: 8 }}>
              Still open on this project, with nobody assigned yet: {result.unfilled_roles.join(', ')}.
            </p>
          )}
        </motion.div>
      )}
    </Panel>
  )
}
