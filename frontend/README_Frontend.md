# ProjectMind AI — Frontend

React 19 + Vite 8 + Tailwind v4 + Framer Motion. Talks to the Flask backend.

## Running

The backend must be running first (see `../backend/README.md`).

```powershell
cd frontend
npm install
npm run dev      # http://localhost:5173
```

```powershell
npm run build    # production bundle into dist/
npm run preview  # serve the built bundle
npm run lint     # oxlint
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
  components/
    Layout.jsx               routes everything through LandingNav/LandingFooter — see below
    landing/                 LandingNav, LandingFooter, LandingHero, WireframeCubes,
                              landing.css — the "Gallery Mono" design tokens (see ../DESIGN.md)
    PageHeader.jsx           the one place a page title is styled
    ProjectCard.jsx          card + relevance/explainability display
    SearchControls.jsx       SearchBar (+ mic button), ExampleQueries, FilterPanel
    ProjectPlanner.jsx       synopsis + roadmap tabs, PDF export, timeline personalisation
    TeamBuilder.jsx          stateless skill-matching role suggestions (no account needed)
    ProjectChat.jsx          project-grounded AI chat widget (only renders if the backend has it enabled)
    MarkdownLite.jsx         dependency-free Markdown renderer for chat replies — renders straight
                             to React elements, no dangerouslySetInnerHTML, since the text is model output
    NotificationsBell.jsx    polls /api/notifications every 30s
    FeedbackForm.jsx         star rating + comment -> POST /api/feedback
    Feedback.jsx             Spinner, ErrorNotice, EmptyState
    ErrorBoundary.jsx        catches render-time exceptions below it in the tree
  pages/                     Search, Browse, ResumeMatch, Chat, Teams, TeamRoom, Account,
                             ProjectDetail, Favorites, History, Analytics, Dashboard, About
```

`Layout.jsx` is now just a thin wrapper: every route (bar `/dashboard`, which
brings its own shell) renders inside `LandingNav` + `LandingFooter`, the same
chrome the marketing landing screen always used — see the "One nav" note
below.

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

**One nav, and it's dark-only.** The app used to run a light/dark Tailwind
theme with its own header, distinct from the marketing landing page's chrome.
Both have since merged into a single "Gallery Mono" identity (see
`../DESIGN.md`) — `LandingNav`/`LandingFooter` are the only chrome in the
app now, and there is no light mode or theme toggle. The feature-link row in
`LandingNav` is hidden specifically on the true landing screen (`/` with no
search run yet) so a first-time visitor sees the clean hero, not a nine-item
menu; every other route keeps the full nav, since it's the only way to reach
most pages. Reduced-motion preferences still disable the Framer Motion
animations.

## Known issue

`npm audit` reports 2 high-severity advisories in `react-router-dom`
(GHSA-qwww-vcr4-c8h2). It is a CSRF bypass in **React Server Components mode**,
affecting server-side actions. This is a pure client-side SPA with no RSC and no
server actions, so the vulnerable path is unreachable. The only offered fix is a
**major-version downgrade** to 7.11.0, which is not worth a functional
regression for a feature we do not use. Re-evaluate if the app ever adopts RSC
or a server-rendered router.
