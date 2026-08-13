/**
 * The one place a page title is styled.
 *
 * Sized and spaced to match the Dashboard/landing hero language — a full
 * t-headline-lg with open space around it, not a small title hugged by a
 * divider — so every page reads as the same design, not a plainer "app"
 * layer bolted underneath the marketing pages.
 */
export default function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <div className="mb-12 flex flex-wrap items-end justify-between gap-6">
      <div className="min-w-0">
        {eyebrow && (
          <span
            className="t-label-caps mb-3 inline-block"
            style={{ color: 'var(--on-surface-variant)', fontSize: 11 }}
          >
            {eyebrow}
          </span>
        )}
        <h1 className="t-headline-lg" style={{ color: 'var(--primary)' }}>
          {title}
        </h1>
        {description && (
          <p className="t-body-md mt-3 max-w-2xl" style={{ color: 'var(--on-surface-variant)' }}>
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
