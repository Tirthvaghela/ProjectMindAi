import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useSearchParams } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import AppSidebar from './AppSidebar'
import NotificationsBell from './NotificationsBell'
import './landing/landing.css'

/**
 * Slim status bar above every app page's content — the same health pill and
 * notifications the old Dashboard-only header had, now universal across
 * every route the sidebar covers (see AppSidebar.jsx).
 */
function TopBar({ onMenuClick }) {
  const { user } = useAuth()
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <header
      className="flex h-16 shrink-0 items-center justify-between gap-3 px-4 sm:px-6"
      style={{ borderBottom: '1px solid var(--border-technical)' }}
    >
      <div className="flex min-w-0 items-center gap-3">
        {/* Sidebar is a fixed off-canvas drawer below `lg` (see AppSidebar.jsx)
            — this is its only open control on those widths. */}
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open menu"
          className="grid h-9 w-9 shrink-0 place-items-center transition hover:bg-white/5 lg:hidden"
          style={{ color: 'var(--on-surface-variant)', border: '1px solid var(--border-technical)', borderRadius: 8 }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 20 }}>
            menu
          </span>
        </button>
        <span
          className="t-label-mono flex min-w-0 items-center gap-2 truncate px-3 py-1.5"
          style={{ color: 'var(--outline)', border: '1px solid var(--border-technical)', borderRadius: 8 }}
        >
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: health?.status === 'ok' ? '#7bcf9f' : health ? '#e3ab6a' : 'var(--outline)' }}
          />
          <span className="truncate">
            Hybrid Search Engine{health ? (health.status === 'ok' ? ' · Online' : ' · Degraded') : ''}
          </span>
        </span>
      </div>
      {user && <NotificationsBell />}
    </header>
  )
}

/**
 * The one bit of chrome the pure marketing landing screen and the sign-in
 * screen get — no sidebar, no Recents, nothing app-shaped. Just enough to
 * get in: the logo, and a way to reach the real app (sign in, or straight
 * to Dashboard if already signed in). Both screens are entry points, not
 * "the app" — a sidebar full of modules you can't use yet (or a Settings
 * link back to the very page you're on) doesn't belong on either.
 */
const LANDING_NAV = [
  { label: 'How It Works', href: '#how-it-works' },
  { label: 'Capabilities', href: '#capabilities' },
  { label: 'Architecture', href: '#architecture' },
]

function BareTopBar() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  // The in-page anchor links only resolve to something on the landing
  // screen itself (its sections live in LandingHero.jsx) — showing them on
  // /account would just be dead links.
  const isLanding = pathname === '/'
  // The account screen names itself instead of showing the Sign in/
  // Dashboard pill — that pill either points right back at the form it's
  // next to (signed out) or is redundant with the page's own "Signed in"
  // state (signed in), same reasoning either way.
  const isAccount = pathname === '/account'

  // Starts transparent over the hero's own black background, then picks up
  // a blurred surface once real page content scrolls underneath it — see
  // .site-header/.scrolled in landing.css.
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`landing-mono site-header sticky top-0 z-40 w-full${scrolled ? ' scrolled' : ''}`}>
      <div className="container-wide flex h-16 items-center justify-between">
        <Link to="/" className="flex shrink-0 items-center gap-2.5">
          <span
            className="grid h-8 w-8 place-items-center text-xs font-bold"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
          >
            PM
          </span>
          <span className="t-headline-md" style={{ color: 'var(--primary)', fontSize: 18 }}>
            ProjectMind AI
          </span>
        </Link>

        {isLanding && (
          <nav className="hidden items-center gap-8 md:flex">
            {LANDING_NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="t-label-mono transition hover:opacity-75"
                style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}
              >
                {item.label}
              </a>
            ))}
          </nav>
        )}

        {isAccount ? (
          <span
            className="t-label-caps hidden shrink-0 items-center gap-2 px-3 py-1.5 sm:flex"
            style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)', color: 'var(--on-surface-variant)', borderRadius: 999, fontSize: 10.5 }}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--primary)' }} />
            ProjectMind / Account access
          </span>
        ) : (
          <Link
            to={user ? '/dashboard' : '/account'}
            className="t-label-caps shrink-0 px-4 py-2 transition hover:opacity-85"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
          >
            {user ? 'Dashboard' : 'Sign in'}
          </Link>
        )}
      </div>
    </header>
  )
}

// Routes that are entirely gated behind an account (see routes/teams.py —
// "every route here requires a signed-in account, unlike the rest of the
// app") — for these specifically, a signed-out visitor is shown the same
// bare, full-bleed entry chrome as /account itself, instead of the full app
// shell wrapped around an inline "please sign in" message. The inline
// message (Teams.jsx's own EmptyState) still renders exactly as before;
// only the surrounding chrome changes, so this never touches routing,
// authorization, or what data is fetched — a signed-out visitor already
// received no team data before this, only the sidebar/topbar around the
// message looked more "logged in" than the page actually was.
const ACCOUNT_GATED_PREFIXES = ['/teams']

/**
 * Two shells, one app.
 *
 * The pure landing screen (index route, no search run yet), the sign-in
 * screen, and a signed-out visit to an account-gated route are all entry
 * points, not "the app" — full-bleed, no sidebar, normal document scroll.
 * Every other route, including "/" the moment a search has run, gets the
 * persistent sidebar shell (see AppSidebar.jsx) instead — that's "dashboard
 * and features," per the design this was built to.
 */
export default function Layout() {
  const { pathname } = useLocation()
  const [searchParams] = useSearchParams()
  const { user, loading: authLoading } = useAuth()
  const isAccountGated = ACCOUNT_GATED_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  const isBareChrome =
    (pathname === '/' && !searchParams.get('q')) ||
    pathname === '/account' ||
    (isAccountGated && !authLoading && !user)

  // Below `lg`, AppSidebar renders as an off-canvas drawer instead of the
  // fixed 256px column — a phone-width viewport can't spare that much
  // width for permanent chrome. Closes on every navigation so it never
  // lingers open over the page the user just went to.
  const [navOpen, setNavOpen] = useState(false)
  useEffect(() => {
    setNavOpen(false)
  }, [pathname])

  if (isBareChrome) {
    return (
      <div className="landing-mono flex min-h-screen flex-col" style={{ background: 'var(--background)' }}>
        <BareTopBar />
        <main className="flex-1">
          <Outlet />
        </main>
      </div>
    )
  }

  return (
    <div className="landing-mono relative flex h-screen overflow-hidden" style={{ background: 'var(--background)' }}>
      <div className="grid-bg pointer-events-none absolute inset-0 z-0" />
      <div className="scanline" />

      {navOpen && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          style={{ background: 'rgba(0,0,0,0.6)' }}
          onClick={() => setNavOpen(false)}
          aria-hidden="true"
        />
      )}
      <AppSidebar open={navOpen} onClose={() => setNavOpen(false)} />

      <div className="relative z-10 flex h-full flex-1 flex-col overflow-hidden">
        <TopBar onMenuClick={() => setNavOpen(true)} />
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
