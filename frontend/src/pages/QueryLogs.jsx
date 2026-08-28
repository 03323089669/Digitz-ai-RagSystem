import React, { useEffect, useMemo, useState } from 'react'
import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000' })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('digitz-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Highly Professional Markdown & Text Cleaner Component
const CleanResponseCell = ({ text }) => {
  if (!text) return <span style={{ color: '#666' }}>—</span>;

  // Cleanup markdown table artifacts and headers for clean preview
  const lines = text
    .split('\n')
    .map(line => line.trim())
    .filter(line => line && !line.startsWith('|---') && !line.startsWith('| ---'))
    .map(line => line.replace(/^#+\s+/, '')) // Remove ## headers
    .map(line => line.replace(/^\|\s*|\s*\|$/g, '')) // Remove outer pipes
    .map(line => line.replace(/\|/g, ' • ')) // Convert inner pipes to beautiful bullets
    .join('\n');

  return (
    <div style={{ 
      maxWidth: '340px', 
      maxHeight: '95px', 
      overflowY: 'auto', 
      fontSize: '13px', 
      lineHeight: '1.5', 
      whiteSpace: 'pre-wrap',
      color: '#e0e0e0',
      paddingRight: '4px'
    }}>
      {lines}
    </div>
  );
};

export default function QueryLogs() {
  const [queries, setQueries] = useState([])
  const [filters, setFilters] = useState({ brand: '', keyword: '', date: '' })
  const [debouncedFilters, setDebouncedFilters] = useState(filters)

  // Debounce setup to prevent heavy database hits on every single character type
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedFilters(filters), 350)
    return () => clearTimeout(handler)
  }, [filters])

  useEffect(() => {
    const token = localStorage.getItem('digitz-token')
    if (!token) return
    api.get('/admin/queries', { params: debouncedFilters })
       .then((res) => setQueries(res.data.queries || []))
       .catch(() => setQueries([]))
  }, [debouncedFilters])

  const rows = useMemo(() => queries, [queries])

  // Clean date formatter (Extracts Date and precise Time clearly)
  const formatDateTime = (isoString) => {
    if (!isoString) return '—';
    const date = new Date(isoString);
    const d = date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
    const t = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    return (
      <div style={{ fontSize: '12px' }}>
        <div style={{ color: '#fff', fontWeight: '500' }}>{d}</div>
        <div style={{ color: '#777', marginTop: '2px' }}>{t}</div>
      </div>
    );
  };

  return (
    <div style={{ 
      background: '#121214', 
      borderRadius: '12px', 
      padding: '24px', 
      boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      border: '1px solid #222'
    }}>
      
      {/* Top Metric Header */}
      <div style={{ display: 'flex', justifyContent: 'between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid #222', paddingBottom: '20px' }}>
        <div>
          <h2 style={{ margin: '0 0 6px 0', fontSize: '20px', fontWeight: '600', color: '#fff', letterSpacing: '-0.3px' }}>Query Logs</h2>
          <p style={{ margin: 0, color: '#8a8f98', fontSize: '13px' }}>
            Audit trail for conversational history, latency tracking, and retrieval precision scores.
          </p>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
        <input 
          style={inputStyle} 
          placeholder="Filter by Brand ID" 
          value={filters.brand} 
          onChange={(e) => setFilters({ ...filters, brand: e.target.value })} 
        />
        <input 
          style={inputStyle} 
          placeholder="Search question/answer..." 
          value={filters.keyword} 
          onChange={(e) => setFilters({ ...filters, keyword: e.target.value })} 
        />
        <input 
          type="date"
          style={{ ...inputStyle, color: filters.date ? '#fff' : '#666' }} 
          value={filters.date} 
          onChange={(e) => setFilters({ ...filters, date: e.target.value })} 
        />
      </div>

      {/* Modern Data Table */}
      <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid #222', background: '#16161a' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ background: '#1e1e24', borderBottom: '1px solid #2d2d35' }}>
              <th style={thStyle}>Question</th>
              <th style={thStyle}>Answer Excerpt</th>
              <th style={thStyle}>Brand</th>
              <th style={thStyle}>Session</th>
              <th style={thStyle}>Timestamp</th>
              <th style={thStyle}>Latency</th>
              <th style={thStyle}>Chunks</th>
              <th style={thStyle}>Similarity</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ padding: '40px', textAlign: 'center', color: '#555', fontSize: '14px' }}>
                  No records found matching the active filters.
                </td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={row.id || index} style={trStyle} className="log-row">
                  {/* Question */}
                  <td style={{ ...tdStyle, color: '#fff', fontWeight: '500', maxWidth: '240px', wordBreak: 'break-word' }}>
                    {row.query_text}
                  </td>
                  
                  {/* Cleaned Answer */}
                  <td style={tdStyle}>
                    <CleanResponseCell text={row.answer_excerpt} />
                  </td>
                  
                  {/* Brand Tag */}
                  <td style={tdStyle}>
                    <span style={{ background: '#22252a', color: '#58a6ff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '600', border: '1px solid #2d3139' }}>
                      {row.brand_key || '—'}
                    </span>
                  </td>
                  
                  {/* Smart Session ID Truncation */}
                  <td style={{ ...tdStyle, fontFamily: 'monospace', color: '#8b949e', fontSize: '12px' }} title={row.session_id}>
                    {row.session_id ? `..${row.session_id.slice(-6)}` : '—'}
                  </td>
                  
                  {/* Timestamp */}
                  <td style={tdStyle}>
                    {formatDateTime(row.created_at)}
                  </td>
                  
                  {/* Performance/Latency Badge */}
                  <td style={tdStyle}>
                    {row.response_time ? (
                      <span style={{ 
                        color: parseFloat(row.response_time) > 3.5 ? '#ff6b6b' : '#34c759',
                        fontWeight: '600',
                        fontSize: '13px'
                      }}>
                        {parseFloat(row.response_time).toFixed(2)}s
                      </span>
                    ) : '—'}
                  </td>
                  
                  {/* Retrieved Chunks count */}
                  <td style={{ ...tdStyle, color: '#c9d1d9', fontWeight: '500', textAlign: 'center' }}>
                    {row.retrieved_chunks ?? '—'}
                  </td>
                  
                  {/* Similarity Score Performance Check */}
                  <td style={tdStyle}>
                    {row.similarity_score ? (
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ 
                          fontWeight: '600', 
                          color: parseFloat(row.similarity_score) > 0.25 ? '#34c759' : '#ff9f0a' 
                        }}>
                          {parseFloat(row.similarity_score).toFixed(4)}
                        </span>
                        <div style={{ 
                          width: '100%', 
                          background: '#222', 
                          height: '3px', 
                          borderRadius: '2px', 
                          marginTop: '4px',
                          overflow: 'hidden'
                        }}>
                          <div style={{ 
                            width: `${Math.min(parseFloat(row.similarity_score) * 100, 100)}%`, 
                            background: parseFloat(row.similarity_score) > 0.25 ? '#34c759' : '#ff9f0a',
                            height: '100%' 
                          }} />
                        </div>
                      </div>
                    ) : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// Design Token Styles for Dashboard Matrix Look
const thStyle = { 
  padding: '14px 16px', 
  fontWeight: '600', 
  fontSize: '12px', 
  color: '#8a8f98', 
  textTransform: 'uppercase', 
  letterSpacing: '0.6px',
  borderBottom: '1px solid #222'
};

const tdStyle = { 
  padding: '16px', 
  borderBottom: '1px solid #1f1f23', 
  verticalAlign: 'top',
  fontSize: '13.5px'
};

const trStyle = { 
  background: '#16161a',
  borderBottom: '1px solid #222'
};

const inputStyle = {
  background: '#1c1c21',
  border: '1px solid #2d2d35',
  color: '#fff',
  padding: '10px 14px',
  borderRadius: '6px',
  outline: 'none',
  fontSize: '13px',
  minWidth: '200px',
  transition: 'border-color 0.2s',
};