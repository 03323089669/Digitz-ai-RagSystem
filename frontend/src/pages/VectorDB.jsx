import React, { useEffect, useState } from 'react'
import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000' })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('digitz-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export default function VectorDB() {
  const [summary, setSummary] = useState({ collections: [], documents: {} })

  useEffect(() => {
    api.get('/ingest/vector-db').then((res) => setSummary(res.data)).catch(() => setSummary({ collections: [], documents: {} }))
  }, [])

  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="section-hd" style={{ marginBottom: 16 }}>
        <h2>Vector Database</h2>
        <p className="small muted">Local ChromaDB collections, document counts, and storage path are surfaced here.</p>
      </div>
      <div style={{ display: 'grid', gap: 12 }}>
        {summary.collections.map((col) => (
          <div key={col.name} className="file-row">
            <div>
              <div className="file-name">{col.name}</div>
              <div className="file-meta">Documents: {col.count}</div>
            </div>
            <div className="badge">Local Chroma</div>
          </div>
        ))}
        {!summary.collections.length && <div className="muted">No collections yet. Upload a document to build the local vector store.</div>}
      </div>
    </div>
  )
}
