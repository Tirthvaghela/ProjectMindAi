import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { setPendingQuery } from '../utils/pendingQuery'

// Difficulty stays monochrome (see DESIGN.md — data is differentiated by
// label and border/text weight, not hue) but still reads at a glance:
// Beginner is dim, Advanced is full-brightness primary.
const DIFFICULTY_STYLES = {
  Beginner: { border: 'var(--border-technical)', color: 'var(--on-surface-variant)' },
  Intermediate: { border: 'var(--outline)', color: 'var(--on-surface)' },
  Advanced: { border: 'var(--primary)', color: 'var(--primary)' },
}

function StarButton({ active, onClick }) {
  return (
    <button
      onClick={(event) => {
        // The card is wrapped in a Link; without this the click navigates
        // away instead of toggling the favourite.
        event.preventDefault()
        event.stopPropagation()
        onClick()
      }}
      aria-label={active ? 'Remove from favourites' : 'Save to favourites'}
      aria-pressed={active}
      className="shrink-0 p-1.5 transition hover:bg-white/5"
      style={{ color: active ? 'var(--primary)' : 'var(--outline)', borderRadius: 6 }}
    >
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill={active ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.8 6.2 20.9l1.1-6.5L2.6 9.8l6.5-.9L12 3z" />
      </svg>
    </button>
  )
}

/**
 * Repository shortcut.
 *
 * A <button> that opens a URL rather than an <a>, because the whole card is
 * already wrapped in a react-router <Link> and nesting an anchor inside an
 * anchor is invalid HTML that browsers resolve unpredictably. The aria-label
 * carries the destination that the markup cannot.
 */
function RepoButton({ url, title }) {
  return (
    <button
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        window.open(url, '_blank', 'noopener,noreferrer')
      }}
      aria-label={`Open the reference repository for ${title} on GitHub in a new tab`}
      title="Reference repository on GitHub"
      className="shrink-0 p-1.5 transition hover:bg-white/5"
      style={{ color: 'var(--outline)', borderRadius: 6 }}
    >
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2A10 10 0 002 12c0 4.42 2.87 8.17 6.84 9.5.5.09.68-.22.68-.48l-.01-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 015 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85l-.01 2.75c0 .27.18.58.69.48A10 10 0 0022 12 10 10 0 0012 2z" />
      </svg>
    </button>
  )
}

/**
 * Relevance display.
 *
 * Showing the raw fused score alone would be meaningless to a student, so we
 * surface *why* it matched: the matched keyword terms come straight from the
 * backend's BM25 half, and a semantic-only match is labelled as such rather
 * than shown as an empty list.
 *
 * `overallScore`/`matchingFactors` are the two fields unique to
 * POST /api/recommend (nlp/recommend.py:personalized_recommend) — plain
 * search results never carry them, so the fallback below (relevance.score +
 * matched-term chips) is exactly the old behaviour. When they ARE present,
 * `overallScore` replaces the raw hybrid score as the headline percent (it
 * already blends relevance with skill/timeline fit) and `matchingFactors`
 * — already-composed strings like "Skill match: you already have Python" —
 * render as the roadmap's own "✓ this matched, ✓ that matched" checklist
 * instead of bare keyword chips.
 */
function RelevanceBar({ relevance, why, overallScore, matchingFactors }) {
  if (!relevance) return null
  const percent = Math.round(overallScore ?? relevance.score * 100)
  const explained = matchingFactors?.length > 0

  return (
    <div className="mt-4 pt-3" style={{ borderTop: '1px solid var(--border-technical)' }}>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
          {explained ? 'Best-fit score' : 'Hybrid match'}
        </span>
        <span className="t-label-mono shrink-0 tabular-nums" style={{ color: 'var(--on-surface)' }}>
          {percent}%
        </span>
      </div>
      <div className="flex items-center gap-2.5">
        {/* Track and fill share a rounded end so the bar reads as one object
            rather than a pill floating in a slot. */}
        <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
          <motion.div
            className="h-full rounded-full"
            style={{ background: 'var(--primary)' }}
            initial={{ width: 0 }}
            animate={{ width: `${percent}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
      </div>

      {why && (
        <p className="t-body-md mt-2.5" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>{why}</p>
      )}

      {explained ? (
        <ul className="mt-2.5 space-y-1">
          {matchingFactors.map((factor) => (
            <li key={factor} className="flex items-start gap-1.5">
              <span className="t-label-mono shrink-0" style={{ color: 'var(--primary)', fontSize: 12 }} aria-hidden="true">✓</span>
              <span className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>{factor}</span>
            </li>
          ))}
        </ul>
      ) : (
        relevance.matched_terms?.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1">
            {relevance.matched_terms.slice(0, 6).map((term) => (
              <span
                key={term}
                className="t-label-mono px-1.5 py-0.5"
                style={{ border: '1px solid var(--primary)', color: 'var(--primary)', fontSize: 11, borderRadius: 4 }}
              >
                {term}
              </span>
            ))}
          </div>
        )
      )}
    </div>
  )
}

/**
 * Secondary actions beyond the card's own click-through ("View Project" is
 * just clicking the card, same as Star/Repo above). Both routes reuse
 * functionality that already exists rather than adding anything new:
 * - Compare hands a natural-language request to the AI assistant
 *   (nlp/chat_tools.py:compare_projects) via the same pendingQuery hand-off
 *   the landing page's search box already uses to carry a query into
 *   Dashboard — the assistant resolves the title and compares it itself,
 *   exactly as it would if a user had typed the same request.
 * - Find Similar deep-links into ProjectDetail's own "Similar projects"
 *   section (api.similar, already rendered there) rather than duplicating
 *   that fetch/section here.
 */
function CardActions({ project }) {
  // <button>, not <Link> — same reasoning as RepoButton above: the whole
  // card is already an <a> (react-router <Link>), and a nested <a> inside
  // it is invalid HTML that browsers resolve unpredictably.
  const navigate = useNavigate()

  const compare = (event) => {
    event.preventDefault()
    event.stopPropagation()
    setPendingQuery(`Compare "${project.title}" with a similar alternative from the catalogue.`)
    navigate('/dashboard')
  }

  const findSimilar = (event) => {
    event.preventDefault()
    event.stopPropagation()
    navigate(`/project/${project.project_id}#similar`)
  }

  return (
    <div className="mt-3 flex items-center gap-3">
      <button
        type="button"
        onClick={compare}
        className="t-label-caps transition hover:opacity-70"
        style={{ color: 'var(--on-surface-variant)', fontSize: 10.5 }}
      >
        Compare
      </button>
      <span style={{ color: 'var(--border-technical)' }}>·</span>
      <button
        type="button"
        onClick={findSimilar}
        className="t-label-caps transition hover:opacity-70"
        style={{ color: 'var(--on-surface-variant)', fontSize: 10.5 }}
      >
        Find Similar
      </button>
    </div>
  )
}

export default function ProjectCard({ project, isFavorite, onToggleFavorite, index = 0 }) {
  const difficultyStyle = DIFFICULTY_STYLES[project.difficulty] ?? DIFFICULTY_STYLES.Beginner

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      // Stagger, but cap it — with 50 results an uncapped delay would leave the
      // last card fading in seconds after the first.
      transition={{ duration: 0.25, delay: Math.min(index * 0.04, 0.3) }}
      className="h-full"
    >
      <Link
        to={`/project/${project.project_id}`}
        className="glass-panel card-hover group flex h-full flex-col p-5 transition duration-200"
        style={{ borderRadius: 8 }}
      >
        <div className="flex items-start justify-between gap-3">
          <h3 className="t-label-mono leading-snug" style={{ color: 'var(--primary)', fontSize: 15 }}>
            {project.title}
          </h3>
          <div className="-mr-1 -mt-1 flex shrink-0 items-center">
            {project.github_url && (
              <RepoButton url={project.github_url} title={project.title} />
            )}
            {onToggleFavorite && (
              <StarButton active={isFavorite} onClick={() => onToggleFavorite(project.project_id)} />
            )}
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <span
            className="t-label-caps px-2 py-0.5"
            style={{ border: `1px solid ${difficultyStyle.border}`, color: difficultyStyle.color, borderRadius: 999, fontSize: 10 }}
          >
            {project.difficulty}
          </span>
          <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 12 }}>{project.domain}</span>
          <span style={{ color: 'var(--border-technical)' }}>·</span>
          <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 12 }}>
            {project.duration_weeks} weeks
          </span>
        </div>

        <p className="t-body-md mt-3 line-clamp-3" style={{ color: 'var(--on-surface-variant)', fontSize: 13.5, lineHeight: 1.6 }}>
          {project.description}
        </p>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {project.technologies?.slice(0, 5).map((tech) => (
            <span
              key={tech}
              className="t-label-mono px-2 py-0.5"
              style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 11, borderRadius: 4 }}
            >
              {tech}
            </span>
          ))}
        </div>

        {/* Pushes the relevance block to the bottom so cards in a row align. */}
        <div className="mt-auto">
          <RelevanceBar
            relevance={project.relevance}
            why={project.why_recommended || project.recommendation_reason}
            overallScore={project.overall_score}
            matchingFactors={project.matching_factors}
          />
          <CardActions project={project} />
        </div>
      </Link>
    </motion.div>
  )
}
