import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// An object literal silently keeps only the LAST of two identical keys, so a
// new endpoint helper can replace an existing one without any error (a second
// `roadmap` once did exactly that). Mocked component tests cannot see it, so
// guard the source of the api object directly.
const source = readFileSync(resolve(process.cwd(), 'src/services/api.js'), 'utf8')

describe('services/api.js', () => {
  it('defines every api method exactly once', () => {
    const start = source.indexOf('export const api = {')
    expect(start).toBeGreaterThan(-1)
    const names = [...source.slice(start).matchAll(/^ {2}([A-Za-z0-9_]+):/gm)].map((m) => m[1])
    expect(names.filter((n, i) => names.indexOf(n) !== i)).toEqual([])
    expect(names.length).toBeGreaterThan(50)
  })

  it('keeps the project roadmap and the personal roadmap as separate methods', () => {
    expect(source).toMatch(/roadmap: \(id\) => client\.get\(`\/project\/\$\{id\}\/roadmap`\)/)
    expect(source).toMatch(/personalRoadmap: \(projectId\) => client\.get\('\/roadmap\/me'/)
  })
})
