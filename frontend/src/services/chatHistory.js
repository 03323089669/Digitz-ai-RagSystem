import axios from 'axios'

const apiBase = import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000'

const api = axios.create({
  baseURL: apiBase,
  timeout: 60000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('digitz-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export async function fetchChatSessionMessages(sessionId) {
  // Prefer new conversations API if present; fallback to legacy query API.
  const token = localStorage.getItem('digitz-token')

  // 1) New backend route (exists in this repo): /api/conversations/{conv_id}/messages
  try {
    const res = await api.get(`/api/conversations/${sessionId}/messages`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (res?.data && Array.isArray(res.data.messages)) return res.data.messages
    if (res?.data?.messages && Array.isArray(res.data.messages)) return res.data.messages
    return []
  } catch (e) {
    // 2) Legacy route used by current ChatViewer (might be missing)
    const legacyRes = await api.get(`/query/sessions/${sessionId}/messages`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    return Array.isArray(legacyRes?.data?.messages) ? legacyRes.data.messages : []
  }
}

