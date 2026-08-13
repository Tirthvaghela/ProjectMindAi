/**
 * The card anatomy Dashboard's quick-action cards and the landing page's
 * "Platform Modules" cards use: an icon box, a divider, then title/body —
 * not just a bare paragraph under a heading. Every feature panel in the app
 * (Team Builder, Plan this project, Filters, ...) routes through this now,
 * so they all read as the same design language instead of a generic
 * title+text box.
 */
export default function Panel({ icon, title, description, actions, children, compact = false, as: Tag = 'div', ...rest }) {
  const iconBox = compact ? 32 : 36
  const iconSize = compact ? 15 : 18
  const pad = compact ? 'p-5' : 'p-6'
  const titleSize = compact ? 14 : 15

  return (
    <Tag className={`glass-panel ${pad}`} style={{ borderRadius: 8 }} {...rest}>
      <div className="flex flex-wrap items-start justify-between gap-4 pb-4" style={{ borderBottom: '1px solid var(--border-technical)' }}>
        <div className="flex min-w-0 items-center gap-3">
          {icon && (
            <div
              className="flex shrink-0 items-center justify-center"
              style={{ width: iconBox, height: iconBox, background: 'var(--surface-container-highest)', border: '1px solid var(--border-technical)', borderRadius: 8 }}
            >
              <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: iconSize }}>
                {icon}
              </span>
            </div>
          )}
          <div className="min-w-0">
            <h2 className="t-label-mono" style={{ color: 'var(--primary)', fontSize: titleSize }}>
              {title}
            </h2>
            {description && (
              <p className="t-body-md mt-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
                {description}
              </p>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="pt-5">{children}</div>
    </Tag>
  )
}
