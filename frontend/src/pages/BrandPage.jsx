import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getUploadedFiles } from '../api/client.js'

export default function BrandPage({ selectedBrand, brands = [] }) {
  const { brandKey } = useParams()
  const navigate = useNavigate()
  const activeKey = brandKey || selectedBrand?.key

  const [files, setFiles] = useState([])
  const [loadingFiles, setLoadingFiles] = useState(true)

  // Find dynamic brand details from brands state
  const brand = brands.find((b) => b.key === activeKey) || selectedBrand || {
    key: activeKey,
    name: activeKey.toUpperCase(),
    color: '#7b6ef6',
    description: '',
    industry: '',
    website: '',
    files: 0,
    queries: 0,
    chunks: 0,
    storage: 0,
  }

  useEffect(() => {
    const fetchBrandFiles = async () => {
      setLoadingFiles(true)
      try {
        const data = await getUploadedFiles(activeKey)
        setFiles(data.files || [])
      } catch (error) {
        console.error('Failed to fetch brand files:', error)
      } finally {
        setLoadingFiles(false)
      }
    }
    if (activeKey) {
      fetchBrandFiles()
    }
  }, [activeKey])

  const brandColor = brand.color || '#7b6ef6'
  const brandInitials = brand.name ? brand.name.slice(0, 2).toUpperCase() : 'BR'

  // Formatted storage size
  const formatBytes = (bytes) => {
    if (!bytes) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  return (
    <div className="brand-page">
      {/* Brand Profile Header */}
      <div className="brand-header" style={{ borderColor: brandColor }}>
        <div 
          className="brand-big-icon" 
          style={{ 
            background: brandColor + '1a', 
            color: brandColor,
            border: `1px solid ${brandColor}40`
          }}
        >
          {brand.logo_url ? (
            <img 
              src={brand.logo_url} 
              alt={brand.name} 
              style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'inherit' }} 
              onError={(e) => { e.target.style.display = 'none'; e.target.parentNode.innerText = brandInitials }}
            />
          ) : (
            brandInitials
          )}
        </div>
        <div>
          <div className="brand-hd-name" style={{ color: 'var(--text)' }}>{brand.name}</div>
          <div className="brand-hd-sub">
            {brand.industry || 'General Industry'} · {brand.website ? (
              <a href={brand.website} target="_blank" rel="noopener noreferrer" style={{ color: brandColor, textDecoration: 'none' }}>
                {brand.website.replace(/^https?:\/\/(www\.)?/, '')}
              </a>
            ) : 'No website listed'}
          </div>
        </div>
        
        {/* Statistics Row */}
        <div className="brand-hd-stats" style={{ marginLeft: 'auto', marginRight: '24px' }}>
          <div>
            <div className="brand-hd-stat-val">{brand.files ?? files.length}</div>
            <div className="brand-hd-stat-lbl">Files</div>
          </div>
          <div>
            <div className="brand-hd-stat-val">{brand.chunks ?? 0}</div>
            <div className="brand-hd-stat-lbl">Vector Chunks</div>
          </div>
          <div>
            <div className="brand-hd-stat-val">{brand.queries ?? 0}</div>
            <div className="brand-hd-stat-lbl">AI Queries</div>
          </div>
          <div>
            <div className="brand-hd-stat-val">{formatBytes(brand.storage)}</div>
            <div className="brand-hd-stat-lbl">Storage</div>
          </div>
        </div>

        <button 
          className="topbar-btn" 
          type="button" 
          onClick={() => navigate('/studio')}
          style={{ background: brandColor, color: '#fff', border: 'none', boxShadow: `0 4px 14px ${brandColor}30` }}
        >
          <i className="ti ti-sparkles" /> Ask AI Studio
        </button>
      </div>

      <div className="grid-2-1" style={{ alignItems: 'start' }}>
        {/* Left Column: Knowledge Base Files */}
        <div className="card">
          <div className="section-hd" style={{ marginBottom: 16 }}>
            <div>
              <h2>Brand Knowledge Directory</h2>
              <p className="small muted">Uploaded materials supporting vector embeddings</p>
            </div>
            <button className="btn-ghost" style={{ fontSize: 12 }} onClick={() => navigate('/vault')}>
              Manage Files
            </button>
          </div>

          {loadingFiles ? (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--muted)' }}>
              <div className="auth-spinner" style={{ margin: '0 auto 12px' }} />
              Loading directories...
            </div>
          ) : files.length > 0 ? (
            <div style={{ display: 'grid', gap: '10px' }}>
              {files.map((file) => (
                <div key={file.id} className="file-row" style={{ padding: '14px 16px' }}>
                  <div className="file-icon" style={{ background: 'var(--bg3)', color: 'var(--brand)' }}>
                    <i className={file.type === 'pdf' ? 'ti ti-file-type-pdf' : file.type === 'doc' ? 'ti ti-file-type-doc' : 'ti ti-table'} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="file-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {file.name}
                    </div>
                    <div className="file-meta">
                      Size: {formatBytes(file.size)} · Uploaded: {file.uploaded_at ? new Date(file.uploaded_at).toLocaleDateString() : 'N/A'}
                    </div>
                  </div>
                  <div className="badge badge-muted" style={{ textTransform: 'uppercase', fontSize: 10 }}>
                    {file.type || 'txt'}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)', background: 'var(--bg2)', borderRadius: 'var(--r-sm)', border: '1px dashed var(--border)' }}>
              <i className="ti ti-folder-open" style={{ fontSize: 32, color: 'var(--faint)', marginBottom: 8, display: 'block' }} />
              <div style={{ color: 'var(--text)', fontWeight: 600, marginBottom: 4 }}>No brand knowledge found</div>
              <p className="small muted" style={{ maxWidth: 280, margin: '0 auto 14px' }}>
                Upload training data in the Data Vault to feed the RAG chatbot context.
              </p>
              <button className="topbar-btn" style={{ margin: '0 auto' }} onClick={() => navigate('/vault')}>
                Upload Document
              </button>
            </div>
          )}
        </div>

        {/* Right Column: Profile & Prompt Metadata */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card-sm">
            <div className="section-hd mb-12">
              <h2>Workspace Blueprint</h2>
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              <div>
                <label className="xsmall muted fw-600" style={{ display: 'block', textTransform: 'uppercase', marginBottom: 4 }}>
                  Company Name
                </label>
                <div className="small fw-500">{brand.name}</div>
              </div>
              <div>
                <label className="xsmall muted fw-600" style={{ display: 'block', textTransform: 'uppercase', marginBottom: 4 }}>
                  Market Sector
                </label>
                <div className="small fw-500">{brand.industry || 'Not Configured'}</div>
              </div>
              <div>
                <label className="xsmall muted fw-600" style={{ display: 'block', textTransform: 'uppercase', marginBottom: 4 }}>
                  Status
                </label>
                <div>
                  <span className="badge" style={{ background: brand.status === 'active' ? 'var(--teal-bg)' : 'var(--bg3)', color: brand.status === 'active' ? 'var(--teal)' : 'var(--muted)' }}>
                    {brand.status || 'Active'}
                  </span>
                </div>
              </div>
              {brand.description && (
                <div>
                  <label className="xsmall muted fw-600" style={{ display: 'block', textTransform: 'uppercase', marginBottom: 4 }}>
                    Identity Summary
                  </label>
                  <p className="small text-muted" style={{ margin: 0, lineHeight: 1.4, color: 'var(--text2)' }}>
                    {brand.description}
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="card-sm">
            <div className="section-hd mb-12">
              <h2>Base Prompt Guidelines</h2>
            </div>
            {brand.ai_prompt ? (
              <pre 
                style={{ 
                  margin: 0, 
                  whiteSpace: 'pre-wrap', 
                  fontSize: 11, 
                  fontFamily: 'var(--font)', 
                  background: 'var(--bg)', 
                  padding: 12, 
                  borderRadius: 'var(--r-sm)', 
                  border: '1px solid var(--border)',
                  color: 'var(--text2)',
                  lineHeight: 1.4
                }}
              >
                {brand.ai_prompt}
              </pre>
            ) : (
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                No custom persona defined. Reverts to the default Digitz AI assistant instructions.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
