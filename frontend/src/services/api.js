import axios from 'axios'

// localStorage throws in Safari Private Browsing and similar locked-down
// contexts — every read/write in this file goes through these so a device
// without storage degrades (a new id/no session each visit) instead of
// crashing the app on first load.
function safeGet(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function safeSet(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode, quota, storage disabled — nothing to do */
  }
}
function safeRemove(key) {
  try {
    localStorage.removeItem(key)
  } catch {
    /* as above */
  }
}

/**
 * Device identity without accounts.
 *
 * The backend keys favourites and history on an X-Device-Id header rather than
 * a user record. We generate a UUID once, persist it in localStorage, and send
 * it on every request. This still exists even now that real accounts do too —
 * favourites/history/personalisation stay device-scoped regardless of whether
 * the caller is signed in, unchanged from before accounts existed.
 */
const DEVICE_KEY = 'projectmind.deviceId'

function newDeviceId() {
  // randomUUID needs a secure context; localhost qualifies, but fall back
  // anyway so the app still works if served over plain HTTP on a LAN IP.
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `dev-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function getDeviceId() {
  let id = safeGet(DEVICE_KEY)
  if (!id) {
    id = newDeviceId()
    safeSet(DEVICE_KEY, id)
  }
  return id
}

/**
 * Start this browser fresh, device-identity-wise — called on sign-out (see
 * hooks/useAuth.jsx) so a shared/public computer doesn't hand the next
 * person to sign in the previous account's device-scoped trail (favourites,
 * history, chat conversations — see the module docstring above). Signing
 * IN deliberately does not do this: an anonymous visitor's favourites are
 * meant to carry over once they create an account, only signing OUT should
 * draw a line under "this device's anonymous data belonged to that session".
 */
export function rotateDeviceId() {
  const id = newDeviceId()
  safeSet(DEVICE_KEY, id)
  return id
}

/**
 * Signed-in identity, for teams and notifications only.
 *
 * A bearer token in localStorage, sent as X-Auth-Token — the same shape as
 * X-Device-Id above, just for a verified person instead of an anonymous
 * browser. See hooks/useAuth.jsx for the React side of this.
 */
const TOKEN_KEY = 'projectmind.authToken'

export function getAuthToken() {
  return safeGet(TOKEN_KEY)
}
export function setAuthToken(token) {
  safeSet(TOKEN_KEY, token)
}
export function clearAuthToken() {
  safeRemove(TOKEN_KEY)
}

// '/api' only resolves correctly behind Vite's dev proxy or a same-origin
// production deploy. If the frontend and backend end up on different origins
// (e.g. Vercel + Render, per the README's deployment section), set
// VITE_API_BASE_URL at build time instead of hardcoding one here.
// 20s used to be tight enough that the backend's one-time NLP warmup (model +
// index load, first request only) could trip it before ever reaching the
// server's own response. The backend now warms up at startup (see
// recommend.warmup() in app.py). 30s was raised from there but STILL too
// tight for the tool-calling model (GROQ_TOOL_MODEL) specifically — a real,
// live idea-generation call was directly measured at ~32s server-side, so
// this endpoint failed with "the server took too long to respond" on
// nearly every attempt (a deterministic near-miss, not flakiness) even
// though the backend itself finished successfully a couple of seconds
// later. Distinct from, and in addition to, the 413/context-too-large
// failure mode investigated separately (see nlp/ai_assistant.py) — both
// surface the same user-facing message, but this one is a plain client
// timeout with nothing to shrink. 60s gives real margin above the measured
// latency.
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 60000,
})

client.interceptors.request.use((config) => {
  config.headers['X-Device-Id'] = getDeviceId()
  const token = getAuthToken()
  if (token) config.headers['X-Auth-Token'] = token
  return config
})

/**
 * Turn axios failures into a single readable message.
 *
 * The backend always returns {error: "..."} on failure, so prefer that over
 * axios's generic "Request failed with status code 500", which tells a user
 * nothing actionable.
 */
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const serverMessage = error.response?.data?.error
    const fix = error.response?.data?.fix
    let message = serverMessage || error.message || 'Something went wrong.'
    if (fix) message += ` (${fix})`
    if (error.code === 'ECONNABORTED') {
      message = 'The server took too long to respond.'
    }
    if (!error.response && error.code !== 'ECONNABORTED') {
      message = 'Cannot reach the server. Is the Flask backend running?'
    }
    const rejected = new Error(message)
    // A stable, machine-readable failure reason (e.g. "LLM_RATE_LIMITED"),
    // when the backend sent one — see routes/helpers.py's ApiError.code.
    // Deliberately a new property, not `.code`: axios's own error already
    // uses `.code` for its own values ("ECONNABORTED" etc, checked above),
    // and that's a different error object than the one being constructed
    // here, so reusing the name would be confusing even though it's safe.
    rejected.serverCode = error.response?.data?.code || null
    rejected.status = error.response?.status || null
    return Promise.reject(rejected)
  },
)

// The backend wraps every success in {data: ...}; unwrap once here so no
// component has to remember to write response.data.data.
const unwrap = (response) => response.data

export const api = {
  health: () => client.get('/health').then(unwrap),

  search: (payload) => client.post('/search', payload).then(unwrap),

  recommend: (payload) => client.post('/recommend', payload).then(unwrap),

  listProjects: (params) => client.get('/projects', { params }).then(unwrap),

  getProject: (id) => client.get(`/project/${id}`).then(unwrap),

  similar: (id, topK = 4) =>
    client.get(`/similar/${id}`, { params: { top_k: topK } }).then(unwrap),

  synopsis: (id) => client.get(`/project/${id}/synopsis`).then(unwrap),

  roadmap: (id) => client.get(`/project/${id}/roadmap`).then(unwrap),

  milestones: (id) => client.get(`/project/${id}/milestones`).then(unwrap),

  timelinePredict: (id, { teamSize, experienceLevel } = {}) =>
    client
      .post('/timeline-predict', {
        project_id: id,
        team_size: teamSize,
        experience_level: experienceLevel || undefined,
      })
      .then(unwrap),

  filters: () => client.get('/filters').then(unwrap),

  skillGap: (projectId, skills) =>
    client.post('/skill-gap', { project_id: projectId, skills }).then(unwrap),

  teamBuilder: (projectId, members) =>
    client.post('/team-builder', { project_id: projectId, members }).then(unwrap),

  // Idea-scoped mirrors of the project-scoped calls above, for the Idea
  // Workspace page (pages/IdeaDetail.jsx) — a generated idea has no
  // project_id (see backend/routes/ideas.py), so each of these sends the
  // idea's own fields directly instead. `idea` is spread as-is; the backend
  // only reads the fields each route actually needs and ignores the rest
  // (originality_score, similar_projects, id, ...), so callers never have to
  // pick fields out themselves.
  ideaSkillGap: (idea, skills) =>
    client.post('/idea/skill-gap', { ...idea, skills }).then(unwrap),

  ideaSynopsis: (idea) => client.post('/idea/synopsis', idea).then(unwrap),

  ideaRoadmap: (idea) => client.post('/idea/roadmap', idea).then(unwrap),

  ideaMilestones: (idea) => client.post('/idea/milestones', idea).then(unwrap),

  ideaTimeline: (idea, { teamSize, experienceLevel } = {}) =>
    client
      .post('/idea/timeline', { ...idea, team_size: teamSize, experience_level: experienceLevel || undefined })
      .then(unwrap),

  ideaTeamBuilder: (idea, members) =>
    client.post('/idea/team-builder', { domain: idea.domain, technologies: idea.technologies, members }).then(unwrap),

  ideaChat: (idea, message, history) =>
    client.post('/idea/chat', { idea, message, history }).then(unwrap),

  learningPath: (skills) => client.post('/learning-path', { skills }).then(unwrap),

  chat: (projectId, message, history) =>
    client.post(`/project/${projectId}/chat`, { message, history }).then(unwrap),

  listConversations: () => client.get('/conversations').then(unwrap),

  createConversation: () => client.post('/conversations').then(unwrap),

  getConversation: (id) => client.get(`/conversations/${id}`).then(unwrap),

  deleteConversation: (id) => client.delete(`/conversations/${id}`).then(unwrap),

  sendConversationMessage: (id, message) =>
    client.post(`/conversations/${id}/messages`, { message }).then(unwrap),

  selectProject: (conversationId, projectId) =>
    client.post(`/conversations/${conversationId}/select-project`, { project_id: projectId }).then(unwrap),

  attachResumeSkills: (conversationId, skills) =>
    client.post(`/conversations/${conversationId}/resume-skills`, { skills }).then(unwrap),

  resumeSuggest: ({ file, text, topK = 10 }) => {
    const params = { top_k: topK }
    if (file) {
      const formData = new FormData()
      formData.append('resume', file)
      return client.post('/resume-suggest', formData, { params }).then(unwrap)
    }
    return client.post('/resume-suggest', { text }, { params }).then(unwrap)
  },

  uniqueness: (title, description, domain, technologies) =>
    client.post('/uniqueness', { title, description, domain, technologies }).then(unwrap),

  addFavorite: (projectId) =>
    client.post('/favorite', { project_id: projectId }).then(unwrap),

  removeFavorite: (projectId) =>
    client.delete(`/favorite/${projectId}`).then(unwrap),

  listFavorites: () => client.get('/favorites').then(unwrap),

  history: (limit = 20) =>
    client.get('/history', { params: { limit } }).then(unwrap),

  clearHistory: () => client.delete('/history').then(unwrap),

  feedback: (payload) => client.post('/feedback', payload).then(unwrap),

  signup: (email, password, name) =>
    client.post('/auth/signup', { email, password, name }).then(unwrap),

  login: (email, password) => client.post('/auth/login', { email, password }).then(unwrap),

  logout: () => client.post('/auth/logout').then(unwrap),

  me: () => client.get('/auth/me').then(unwrap),

  // {name?, email?, current_password?, new_password?} — whichever fields are
  // present get updated; the account is always whichever one the auth token
  // resolves to server-side, never one supplied here (see routes/auth.py).
  updateProfile: (payload) => client.patch('/auth/me', payload).then(unwrap),

  createTeam: (projectId, name) =>
    client.post('/teams', { project_id: projectId, name }).then(unwrap),

  // Idea-backed team — a generated idea has no project_id (see
  // backend/routes/ideas.py), so the team is grounded in the idea's own
  // fields directly instead (backend/routes/teams.py, backend/teams/service.py).
  createIdeaTeam: (idea, name) => client.post('/teams', { idea, name }).then(unwrap),

  joinTeam: (inviteCode) => client.post('/teams/join', { invite_code: inviteCode }).then(unwrap),

  myTeams: () => client.get('/teams/mine').then(unwrap),

  getTeam: (teamId) => client.get(`/teams/${teamId}`).then(unwrap),

  // Owner-only — backend/teams/service.py:update_team enforces it, this just
  // surfaces whatever error that rejection comes back as.
  updateTeam: (teamId, name) => client.patch(`/teams/${teamId}`, { name }).then(unwrap),

  // Same endpoint for both "I'm leaving" (targetUserId === your own id) and
  // "owner removes someone else" — backend/teams/service.py:remove_member
  // tells the two apart and enforces who's allowed to do which.
  removeMember: (teamId, targetUserId) => client.delete(`/teams/${teamId}/members/${targetUserId}`).then(unwrap),

  // Self-service — records only the caller's own skills for this team, feeds
  // GET /teams/<id>/roles below (backend/teams/service.py:set_member_skills).
  setMemberSkills: (teamId, skills) => client.post(`/teams/${teamId}/skills`, { skills }).then(unwrap),

  // Role suggestions for this team's real, persisted roster — the
  // POST /api/team-builder flavour reads a typed-in member list instead.
  teamRoles: (teamId) => client.get(`/teams/${teamId}/roles`).then(unwrap),

  teamMessages: (teamId) => client.get(`/teams/${teamId}/messages`).then(unwrap),

  postTeamMessage: (teamId, content) =>
    client.post(`/teams/${teamId}/messages`, { content }).then(unwrap),

  notifications: (limit = 30) => client.get('/notifications', { params: { limit } }).then(unwrap),

  markNotificationRead: (id) => client.post(`/notifications/${id}/read`).then(unwrap),

  markAllNotificationsRead: () => client.post('/notifications/read-all').then(unwrap),
}

export default api
