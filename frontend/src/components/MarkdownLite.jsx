/**
 * Minimal Markdown renderer for LLM chat replies.
 *
 * Deliberately not a full Markdown library: chat replies only ever use a
 * small subset (paragraphs, bold/italic, inline code, fenced code blocks,
 * links, bullet/numbered lists, GFM tables), and rendering straight to React
 * elements — instead of building an HTML string and injecting it — means
 * there is no dangerouslySetInnerHTML and nothing to sanitize, which matters
 * here because this text comes from a model, not from this app's own authors.
 */

function isTableSeparatorRow(line) {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) return false
  // Cells made only of dashes/colons (alignment markers) and pipes — the
  // row GFM tables use to separate the header from the body.
  return /^\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?$/.test(trimmed)
}

function splitTableRow(line) {
  let trimmed = line.trim()
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1)
  if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1)
  return trimmed.split('|').map((cell) => cell.trim())
}

/** A table gets its own layout, not the paragraph fallback's `\n` → space
 * collapse — that collapse is exactly what turned a real table into one
 * unreadable run-on line before this existed. */
function renderTable(lines, key) {
  const headers = splitTableRow(lines[0])
  const rows = lines.slice(2).map(splitTableRow)

  return (
    <div key={key} className="overflow-x-auto" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th
                key={i}
                className="whitespace-nowrap px-3 py-2"
                style={{
                  color: 'var(--on-surface)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  background: 'var(--surface-container-high)',
                  borderBottom: '1px solid var(--border-technical)',
                }}
              >
                {renderInline(h, `${key}-h-${i}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className="px-3 py-2 align-top"
                  style={{ color: 'var(--on-surface-variant)', borderTop: '1px solid var(--border-technical)' }}
                >
                  {renderInline(cell, `${key}-${ri}-${ci}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderInline(text, keyPrefix) {
  const regex = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)\s]+\))/g
  const nodes = []
  let lastIndex = 0
  let match
  let i = 0

  while ((match = regex.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index))
    const token = match[0]
    const key = `${keyPrefix}-${i++}`

    if (token.startsWith('`')) {
      nodes.push(
        <code
          key={key}
          className="px-1 py-0.5 font-mono text-[0.85em]"
          style={{ background: 'var(--surface-container-high)', color: 'var(--on-surface)', borderRadius: 4 }}
        >
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={key} style={{ color: 'var(--on-surface)' }}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('[')) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)
      nodes.push(
        <a
          key={key}
          href={linkMatch[2]}
          target="_blank"
          rel="noreferrer"
          className="underline underline-offset-2 transition hover:no-underline"
          style={{ color: 'var(--primary)' }}
        >
          {linkMatch[1]}
        </a>,
      )
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    }
    lastIndex = regex.lastIndex
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return nodes
}

// ATX heading on its own paragraph, e.g. "### Comparison: ..." — the model
// reaches for these constantly when framing a roadmap/comparison/idea
// (see nlp/ai_assistant.py's DISCOVERY vs IDEATION guidance), so a
// heading-less renderer left the literal "###" on screen.
const HEADING_SIZE_BY_LEVEL = { 1: 16, 2: 15, 3: 14, 4: 13, 5: 12.5, 6: 12 }

function renderBlock(block, key) {
  const lines = block.split('\n').filter((l) => l.trim())
  const headingMatch = lines.length === 1 && lines[0].match(/^(#{1,6})\s+(.*)$/)
  const isTable = lines.length >= 2 && lines[0].includes('|') && isTableSeparatorRow(lines[1])
  const isBulletList = lines.length > 0 && lines.every((l) => /^\s*[-*]\s+/.test(l))
  const isNumberedList = lines.length > 0 && lines.every((l) => /^\s*\d+[.)]\s+/.test(l))

  if (headingMatch) {
    const level = headingMatch[1].length
    return (
      <p
        key={key}
        className="font-semibold"
        style={{ color: 'var(--on-surface)', fontSize: HEADING_SIZE_BY_LEVEL[level] ?? 13 }}
      >
        {renderInline(headingMatch[2], `${key}-h`)}
      </p>
    )
  }
  if (isTable) {
    return renderTable(lines, key)
  }
  if (isBulletList) {
    return (
      <ul key={key} className="list-disc space-y-1 pl-5">
        {lines.map((l, i) => (
          <li key={i}>{renderInline(l.replace(/^\s*[-*]\s+/, ''), `${key}-${i}`)}</li>
        ))}
      </ul>
    )
  }
  if (isNumberedList) {
    return (
      <ol key={key} className="list-decimal space-y-1 pl-5">
        {lines.map((l, i) => (
          <li key={i}>{renderInline(l.replace(/^\s*\d+[.)]\s+/, ''), `${key}-${i}`)}</li>
        ))}
      </ol>
    )
  }
  return <p key={key}>{renderInline(block.replace(/\n/g, ' '), `${key}`)}</p>
}

export default function MarkdownLite({ content, className = '' }) {
  if (!content) return null

  const fenceRegex = /```(\w*)\n?([\s\S]*?)```/g
  const parts = []
  let lastIndex = 0
  let match

  while ((match = fenceRegex.exec(content))) {
    if (match.index > lastIndex) parts.push({ type: 'text', body: content.slice(lastIndex, match.index) })
    parts.push({ type: 'code', body: match[2].replace(/\n$/, '') })
    lastIndex = fenceRegex.lastIndex
  }
  if (lastIndex < content.length) parts.push({ type: 'text', body: content.slice(lastIndex) })

  let blockKey = 0

  return (
    <div className={`space-y-2 ${className}`}>
      {parts.map((part) =>
        part.type === 'code' ? (
          <pre
            key={blockKey++}
            className="overflow-x-auto px-3 py-2.5 text-xs leading-relaxed"
            style={{ background: 'var(--surface-container-lowest)', color: 'var(--on-surface)', border: '1px solid var(--border-technical)', borderRadius: 8 }}
          >
            <code>{part.body}</code>
          </pre>
        ) : (
          part.body
            .split(/\n{2,}/)
            .map((b) => b.trim())
            .filter(Boolean)
            .map((b) => renderBlock(b, blockKey++))
        ),
      )}
    </div>
  )
}
