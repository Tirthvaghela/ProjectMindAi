# ProjectMind AI — Frontend

React 19 + Vite 8 + Tailwind v4 + Framer Motion. Talks to the Flask backend.

## Running

The backend must be running first (see `../backend/README_Backend.md`).

```powershell
cd frontend
npm install
npm run dev      # http://localhost:5173
```

```powershell
npm run build        # production bundle into dist/
npm run preview      # serve the built bundle
npm run lint         # oxlint
npm run test         # Vitest + React Testing Library (run once, CI-style)
npm run test:watch   # same, in watch mode
```

> Vite binds to `localhost`, which resolves to IPv6 `::1` on Windows. Use
> `http://localhost:5173`, not `http://127.0.0.1:5173` — the latter has nothing
> listening on it and will hang.

## Structure

```
src/
  App.jsx                    routes
  services/api.js            axios client, device + auth identity, error normalising
  utils/pdf.js                jsPDF export for the synopsis/roadmap panels
  hooks/
    useFavorites.js           favourite set + optimistic toggle
    useVoiceSearch.js         SpeechRecognition wrapper for the mic button
    useAuth.jsx                signed-in state as context (teams + notifications only)
  test/                      setup.js (jest-dom matchers, scrollIntoView polyfill for jsdom),
                              testUtils.jsx (renderWithProviders: Router + real AuthProvider)
  components/
    ChatPrimitives.jsx       CopyButton, TypingDots — shared by Dashboard.jsx and ProjectChat.jsx
    Layout.jsx               two chrome modes: bare (BareTopBar only — the landing screen with
                              no search yet, /account, and a signed-out visit to an account-gated
                              route like /teams) vs full (AppSidebar + TopBar) for everything else
    landing/                 LandingHero, ShaderBackground, WireframeCubes,
                              landing.css — the "Gallery Mono" design tokens (see ../DESIGN.md)
    PageHeader.jsx           the one place a page title is styled
    ProjectCard.jsx          card + relevance/explainability display
    SearchControls.jsx       SearchBar (+ mic button), ExampleQueries, FilterPanel
    RecommendedForYou.jsx    "Best fit for you" panel on Search — calls /api/recommend
    ProjectPlanner.jsx       synopsis + roadmap tabs, PDF export, timeline personalisation
    TeamBuilder.jsx          stateless skill-matching role suggestions (no account needed) —
                             also exports AssignmentCard, reused by TeamRoom's live-roster version
    StartTeamWorkspace.jsx   shared "start a team" control — posts a project_id (ProjectDetail)
                             or a generated idea (IdeaDetail) to the same POST /api/teams
    SkillGapPanel.jsx        readiness-check panel, shared between ProjectDetail and IdeaDetail
    GeneratedIdeaCard.jsx    AI-idea card used on Dashboard
    BlueprintCard.jsx        AI-idea card used on Ideate (own layout — action row, meta icons, badge)
    Modal.jsx, AuthGateModal.jsx   dialogs with real focus management (see useFocusTrap below)
    ProjectChat.jsx          project-grounded AI chat widget (only renders if the backend has it enabled)
    MarkdownLite.jsx         dependency-free Markdown renderer for chat replies — renders straight
                             to React elements, no dangerouslySetInnerHTML, since the text is model output
    NotificationsBell.jsx    polls /api/notifications every 30s; per-item and "mark all" read
    FeedbackForm.jsx         star rating + comment -> POST /api/feedback
    Feedback.jsx             Spinner, ErrorNotice, EmptyState
    ErrorBoundary.jsx        catches render-time exceptions below it in the tree
    useFocusTrap.js          hook: Escape-to-close, Tab cycling confined to a dialog, focus
                             restored to the trigger on close — used by Modal.jsx/AuthGateModal.jsx
  pages/                     Search, Ideate, IdeaDetail, ResumeMatch, UniquenessCheck, Teams,
                             TeamRoom, Account, ProjectDetail, Favorites, History, Dashboard
```

## Deployment

`VITE_API_BASE_URL` (build-time env var) overrides the default `/api` base
path — needed whenever the frontend and backend are on different origins
(e.g. Vercel for this app, Render for the backend, per the root README). Left
unset, requests go to `/api`, which only resolves via Vite's dev proxy or a
same-origin production deploy.

## Notes on the implementation

**Dev proxy, not CORS.** `vite.config.js` proxies `/api` to `127.0.0.1:5000`,
so in development the browser sees one origin and CORS never applies. The
backend's CORS config still matters if the two are deployed separately.

**Search query lives in the URL.** `/?q=...` means a result set can be
bookmarked, shared, and survives refresh; the History page links straight back
into a previous search using the same mechanism.

**Optimistic favourites.** `useFavorites` updates local state immediately and
rolls back if the request fails. A star that silently does nothing is worse
than one that visibly reverts.

**Personalisation is visible and reversible.** When the backend reports that a
device's own saves and searches moved the ranking, the results header says so
and offers a one-click "Turn off". Personalisation a user can neither see nor
disable is indistinguishable from the ranking simply being wrong. The preference
lives in component state rather than the URL — it is about how *you* see
results, so a shared link should not carry it.

**Technology filter holds several values.** The backend has always matched a
list with ANY semantics; the UI sends multiple as removable chips. Chips plus an
"add" picker rather than a native multi-select, because the corpus has ~88
technologies and a multi-select that long is unreadable and painful on touch.

**Relevance is explained, not just scored.** Cards show the match percentage
*and* the keyword terms that matched, taken from the backend's BM25 half. A
semantically-matched result with no shared keywords is labelled as such rather
than showing an empty list.

**One design identity, two chrome modes, no theme toggle.** The whole app
shares a single dark "Gallery Mono" identity (see `../DESIGN.md`) — there is
no light mode. `Layout.jsx` picks between a bare, full-bleed shell
(`BareTopBar` only — no sidebar) and the full app shell (`AppSidebar` +
`TopBar`) per route, not per theme: bare chrome is for entry points — the
true landing screen (`/` with no search run yet), `/account`, and (since the
protected-page-UX fix) a signed-out visit to an account-gated route like
`/teams`, so a visitor who isn't signed in gets a clean entry screen instead
of the full sidebar/workspace shell wrapped around an inline "please sign
in" message. Every other route gets the full shell. Reduced-motion
preferences still disable the Framer Motion animations throughout.

## Testing

Vitest + React Testing Library (`npm run test`), jsdom environment
(`vite.config.js`'s own `test` block — no second config file). Two things
worth knowing before adding more:

- **Mock `services/api.js` with a *partial* factory, not a blanket
  `vi.mock('../services/api')`.** The bare form auto-mocks every export,
  including the named `getAuthToken`/`setAuthToken`/`getDeviceId`/
  `rotateDeviceId` helpers `hooks/useAuth.jsx` imports directly — those are
  plain, real localStorage wrappers, not network calls, and stubbing them
  out silently breaks every "signed in" test scenario (`getAuthToken()`
  always returns `undefined` regardless of what's actually in
  `localStorage`, so `useAuth` never calls `api.me()`). Every test file so
  far uses the same inline factory: `vi.mock('../services/api', async
  (importOriginal) => { const actual = await importOriginal(); return
  {...actual, default: Object.fromEntries(Object.keys(actual.default).map(k
  => [k, vi.fn()]))} })` — real named exports, mocked default-object
  methods only. It has to be inlined per file (not imported from a shared
  helper): Vitest hoists `vi.mock(...)` above every import in the file,
  including an import of the factory itself, so a shared factory function
  triggers "Cannot access '...' before initialization".
- **jsdom implements no `scrollIntoView`, no real layout.** A no-op stub for
  the former lives in `src/test/setup.js` — components that scroll a
  message list into view (Dashboard.jsx) would otherwise throw in any test
  that renders them.

## Known issue

None currently tracked — `npm audit` reports 0 vulnerabilities as of the
Vitest/React Testing Library addition above.
