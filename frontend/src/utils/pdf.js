import { jsPDF } from 'jspdf'

const MARGIN = 18
const LINE_HEIGHT = 5.2
const PAGE_HEIGHT = 297 // A4, mm

/**
 * Minimal flowing-text PDF writer for the synopsis/roadmap exports.
 *
 * jsPDF's core API is line-by-line with no built-in page-break handling for
 * wrapped paragraphs, so this tracks a vertical cursor and starts a new page
 * itself — hand-rolled rather than pulling in the autotable plugin for what
 * is, structurally, just headings, paragraphs and bullet lists.
 */
class PdfWriter {
  constructor(title) {
    this.doc = new jsPDF({ unit: 'mm', format: 'a4' })
    this.width = this.doc.internal.pageSize.getWidth() - MARGIN * 2
    this.y = MARGIN
    this._title(title)
  }

  _title(title) {
    this.doc.setFont('helvetica', 'bold')
    this.doc.setFontSize(16)
    this.doc.setTextColor(20)
    const lines = this.doc.splitTextToSize(title, this.width)
    this.doc.text(lines, MARGIN, this.y)
    this.y += lines.length * 7 + 4
    this.doc.setDrawColor(200)
    this.doc.line(MARGIN, this.y, MARGIN + this.width, this.y)
    this.y += 8
  }

  _ensureSpace(lines) {
    if (this.y + lines * LINE_HEIGHT > PAGE_HEIGHT - MARGIN) {
      this.doc.addPage()
      this.y = MARGIN
    }
  }

  heading(text) {
    this._ensureSpace(2)
    this.doc.setFont('helvetica', 'bold')
    this.doc.setFontSize(11)
    this.doc.setTextColor(15, 118, 134) // brand teal, matches the app accent
    this.doc.text(text.toUpperCase(), MARGIN, this.y)
    this.y += LINE_HEIGHT + 1
  }

  paragraph(text) {
    this.doc.setFont('helvetica', 'normal')
    this.doc.setFontSize(10)
    this.doc.setTextColor(50)
    const lines = this.doc.splitTextToSize(text, this.width)
    this._ensureSpace(lines.length)
    this.doc.text(lines, MARGIN, this.y)
    this.y += lines.length * LINE_HEIGHT + 4
  }

  bulletList(items) {
    this.doc.setFont('helvetica', 'normal')
    this.doc.setFontSize(10)
    this.doc.setTextColor(50)
    for (const item of items) {
      const lines = this.doc.splitTextToSize(`-  ${item}`, this.width)
      this._ensureSpace(lines.length)
      this.doc.text(lines, MARGIN, this.y)
      this.y += lines.length * LINE_HEIGHT + 1
    }
    this.y += 3
  }

  save(filename) {
    this.doc.save(filename)
  }
}

function slug(text) {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '') || 'project'
  )
}

export function synopsisToPdf(synopsis) {
  const writer = new PdfWriter(synopsis.title)

  writer.heading('Abstract')
  writer.paragraph(synopsis.abstract)

  writer.heading('Problem statement')
  writer.paragraph(synopsis.problem_statement)

  writer.heading('Objectives')
  writer.bulletList(synopsis.objectives)

  writer.heading('Scope')
  writer.paragraph(synopsis.scope)

  writer.heading('Methodology')
  writer.bulletList(synopsis.methodology)

  writer.heading('Modules')
  writer.bulletList(synopsis.modules)

  writer.heading('Technology stack')
  writer.paragraph(synopsis.technology_stack.join(', '))

  writer.heading('Expected results')
  writer.bulletList(synopsis.expected_results)

  writer.heading('Future scope')
  writer.bulletList(synopsis.future_scope)

  writer.save(`${slug(synopsis.title)}-synopsis.pdf`)
}

export function roadmapToPdf({ title, total_weeks, phases }) {
  const writer = new PdfWriter(`${title} — Development Roadmap`)

  writer.paragraph(
    `Total duration: ${total_weeks} week${total_weeks === 1 ? '' : 's'}, across ${phases.length} phases.`,
  )

  phases.forEach((phase, index) => {
    writer.heading(`${index + 1}. ${phase.phase} — ${phase.weeks} week${phase.weeks === 1 ? '' : 's'}`)
    writer.paragraph(phase.description)
    if (phase.tasks?.length > 0) writer.bulletList(phase.tasks)
    if (phase.expected_output) writer.paragraph(`Output: ${phase.expected_output}`)
  })

  writer.save(`${slug(title)}-roadmap.pdf`)
}

export function milestonesToPdf({ title, total_weeks: totalWeeks, milestones }) {
  const writer = new PdfWriter(`${title} — Milestones`)

  writer.paragraph(
    `${milestones.length} checkpoint${milestones.length === 1 ? '' : 's'} across ${totalWeeks} week${totalWeeks === 1 ? '' : 's'}.`,
  )
  writer.bulletList(milestones.map((m) => `${m.id} — ${m.title} (week ${m.week})`))

  writer.save(`${slug(title)}-milestones.pdf`)
}
