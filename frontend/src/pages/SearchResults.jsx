import React, { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { searchBackend } from '../api/client.js'

function useQuery() {
  return new URLSearchParams(useLocation().search)
}

export default function SearchResults({ selectedBrand }) {
  const queryParams = useQuery()
  const query = queryParams.get('query') || ''
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('Search across all brand documents and AI knowledge.')

  useEffect(() => {
    if (!query) {
      setResults([])
      setMessage('Enter a search term to see results.')
      return
    }

    const fetchResults = async () => {
      setLoading(true)
      setMessage('Searching Digitz AI...')
      try {
          const data = await searchBackend(query, selectedBrand?.key)
      } finally {
        setLoading(false)
      }
    }

    fetchResults()
  }, [query])

  return (
    <div className="search-page">
      <div className="card mb-20">
        <div className="section-hd" style={{ marginBottom: '14px' }}>
          <div>
            <h2>Search Results</h2>
            <span className="xsmall muted">Querying across all brands, files, and AI memory.</span>
          </div>
        </div>
        <div className="file-meta" style={{ marginBottom: '18px' }}>
          Search term: <strong>{query || '—'}</strong>
        </div>
        {loading ? (
          <div className="file-meta">Loading...</div>
        ) : (
          <div style={{ display: 'grid', gap: '12px' }}>
            {results.map((item, index) => (
              <div key={`${item.title}-${index}`} className="file-row">
                <div>
                  <div className="file-name">{item.title}</div>
                  <div className="file-meta">{item.subtitle}</div>
                </div>
                <div className="badge" style={{ background: 'var(--bg3)', color: 'var(--brand)' }}>{item.brand}</div>
              </div>
            ))}
            {!results.length && <div className="file-meta">{message}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
