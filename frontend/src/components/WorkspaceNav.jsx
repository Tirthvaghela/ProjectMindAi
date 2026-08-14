// Anchors into the sections both the catalogue project workspace
// (pages/ProjectDetail.jsx) and the generated-idea workspace
// (pages/IdeaDetail.jsx) share — the page grew long enough (overview, skill
// gap, planner, team, chat, similar) that jumping straight to one is worth a
// click, not a rebuild of any of them. Shared here rather than duplicated so
// the two workspaces can never drift out of sync on what sections exist.
export const WORKSPACE_SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'skill-gap', label: 'Skill Gap' },
  { id: 'plan', label: 'Synopsis & Roadmap' },
  { id: 'team', label: 'Team' },
  { id: 'mentor', label: 'AI Mentor' },
  { id: 'similar', label: 'Similar' },
]

// A plain `<a href="#id">` click performs a real browser same-document
// navigation to scroll to the fragment — which pushes a NEW history entry
// carrying no state, discarding whatever the current entry had (confirmed
// live: IdeaDetail.jsx's location.state.idea, the only place a generated
// idea's data lives — see nlp/ai_assistant.py's module docstring — was gone
// after clicking a tab, showing the "idea isn't available anymore" empty
// state on a page that had just loaded fine). ProjectDetail.jsx never
// noticed because it re-fetches by :id on every render regardless of state.
// Scrolling manually and using replaceState (not pushState) with the
// CURRENT history.state carried forward sidesteps this: the visible #hash
// still updates for deep-linking (e.g. ProjectCard's "Find Similar" button),
// but no history entry is created and nothing already on it is dropped.
function scrollToSection(event, id) {
  event.preventDefault()
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  window.history.replaceState(window.history.state, '', `#${id}`)
}

export default function WorkspaceNav() {
  return (
    <nav className="sticky top-0 z-10 -mx-6 flex gap-1 overflow-x-auto px-6 py-2 backdrop-blur-sm" style={{ background: 'color-mix(in srgb, var(--background) 92%, transparent)', borderBottom: '1px solid var(--border-technical)' }}>
      {WORKSPACE_SECTIONS.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          onClick={(event) => scrollToSection(event, s.id)}
          className="t-label-mono shrink-0 whitespace-nowrap px-3 py-1.5 transition hover:opacity-75"
          style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}
        >
          {s.label}
        </a>
      ))}
    </nav>
  )
}
