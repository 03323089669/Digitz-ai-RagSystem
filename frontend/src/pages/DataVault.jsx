import React, { useEffect, useRef, useState } from 'react'
import { uploadFile, deleteUploadedFile, getUploadedFiles, getUploadSummary, resetUploads } from '../api/client.js'

export default function DataVault({ selectedBrand, onRefreshSummary, brands = [], onBrandChange }) {
  const [uploading, setUploading] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadMessage, setUploadMessage] = useState('Select a file and brand to upload')
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [summary, setSummary] = useState({ total_docs: 0, total_queries: 0, total_active_brands: 0, brands: [] })
  const [refreshing, setRefreshing] = useState(false)
  
  // Search & Filters state
  const [searchTerm, setSearchTerm] = useState('')
  const [renameFileId, setRenameFileId] = useState(null)
  const [renameTitle, setRenameTitle] = useState('')
  
  // Modal Preview state
  const [previewFile, setPreviewFile] = useState(null)
  const [previewContent, setPreviewContent] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)

  const fileInputRef = useRef(null)

  // Single source of truth: whatever brand is active app-wide is what you upload
  // to and view here. This used to be two independent dropdowns (Upload Brand /
  // View Brand) that could point at different brands, which made uploaded files
  // silently "disappear" — you'd upload to Brand A while still viewing Brand B.
  const vaultBrand = selectedBrand.key

  const loadVaultData = async () => {
    try {
      const [filesResponse, summaryResponse] = await Promise.all([
        getUploadedFiles(vaultBrand),
        getUploadSummary(),
      ])
      setUploadedFiles(filesResponse.files)
      setSummary(summaryResponse)
    } catch (error) {
      console.error('Failed to load uploaded files', error)
    }
  }

  useEffect(() => {
    loadVaultData()
  }, [vaultBrand, uploading, refreshing])

  const selectedBrandSummary = summary.brands.find((item) => item.key === vaultBrand) ?? { docs: 0, files: 0, queries: 0, content: 0 }
  
  // Search and filter logic
  // NOTE: file.name is guarded with `|| ''` because when the backend returns
  // an incomplete/unauthenticated response (e.g. a failed login upstream),
  // some file entries can come back with name undefined/null, which used to
  // crash the whole component with "Cannot read properties of undefined
  // (reading 'toLowerCase')".
  const filteredFiles = uploadedFiles.filter((file) => {
    const matchesBrand = file.brand_key === vaultBrand
    const matchesSearch = (file.name || '').toLowerCase().includes(searchTerm.toLowerCase())
    return matchesBrand && matchesSearch
  })

  const stats = [
    { label: 'Files', value: selectedBrandSummary.files },
    { label: 'AI Queries', value: selectedBrandSummary.queries },
    { label: 'Indexed Documents', value: selectedBrandSummary.docs },
    { label: 'Content Pieces', value: selectedBrandSummary.content },
  ]

  const handleFileChange = (event) => {
    setSelectedFile(event.target.files?.[0] ?? null)
  }

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadMessage('Please choose a file before uploading.')
      return
    }

    setUploading(true)
    setUploadMessage('Uploading file...')

    try {
      const result = await uploadFile(selectedFile, vaultBrand)
      setUploadMessage(`Uploaded ${result.filename} to ${vaultBrand}. Content size: ${result.content_size} bytes.`)
      setSelectedFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      setRefreshing((prev) => !prev)
      if (typeof onRefreshSummary === 'function') {
        onRefreshSummary()
      }
    } catch (error) {
      console.error('Upload failed', error)
      const detail = error?.response?.data?.detail || error?.response?.data?.message
      if (detail) {
        setUploadMessage(`Upload failed: ${detail}`)
      } else if (error?.code === 'ECONNABORTED' || String(error?.message || '').toLowerCase().includes('timeout')) {
        setUploadMessage('Upload failed: request timed out. Try with a smaller file or retry. (Indexing can take time.)')
      } else {
        setUploadMessage(error?.message ? `Upload failed: ${error.message}` : 'Upload failed. Please try again.')
      }
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteFile = async (fileId) => {
    if (!window.confirm("Are you sure you want to remove this document from the knowledge base?")) return;
    setRefreshing(true)
    try {
      await deleteUploadedFile(fileId)
      setUploadMessage('File removed and dashboard summary updated.')
      setRefreshing((prev) => !prev)
      if (typeof onRefreshSummary === 'function') {
        onRefreshSummary()
      }
    } catch (error) {
      console.error('Failed to delete file', error)
      setUploadMessage('Remove failed. Please try again.')
    } finally {
      setRefreshing(false)
    }
  }

  const handleOpenPreview = async (file) => {
    setPreviewFile(file)
    setPreviewLoading(true)
    setPreviewContent('')
    try {
      const token = localStorage.getItem('digitz-token')
      const apiBase = import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000'
      const response = await fetch(`${apiBase}/ingest/files/${file.id}/preview`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      })
      if (response.ok) {
        const text = await response.text()
        setPreviewContent(text)
      } else {
        setPreviewContent('Failed to load file preview.')
      }
    } catch (error) {
      console.error('Failed to load preview', error)
      setPreviewContent('Error loading preview content.')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleRename = async (fileId) => {
    if (!renameTitle.trim()) return
    try {
      const token = localStorage.getItem('digitz-token')
      const apiBase = import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000'
      const formData = new FormData()
      formData.append('new_title', renameTitle)
      
      const response = await fetch(`${apiBase}/ingest/files/${fileId}`, {
        method: 'PUT',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData
      })
      if (response.ok) {
        setRenameFileId(null)
        setRenameTitle('')
        loadVaultData()
      } else {
        alert('Rename failed')
      }
    } catch (error) {
      console.error('Rename failed', error)
    }
  }

  const handleDownload = (file) => {
    const token = localStorage.getItem('digitz-token')
    const apiBase = import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000'
    const url = `${apiBase}/ingest/files/${file.id}/download`
    
    // Simple fetch and download attachment
    fetch(url, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    })
    .then(resp => resp.blob())
    .then(blob => {
      const link = document.createElement('a')
      link.href = window.URL.createObjectURL(blob)
      link.download = file.name.endsWith('.pdf') ? file.name : `${file.name}.txt`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    })
    .catch(err => console.error('Download failed', err))
  }

  const handleReset = async () => {
    if (!window.confirm("WARNING: This will delete ALL files and vectors across ALL brands. Proceed?")) return;
    setRefreshing(true)
    try {
      await resetUploads()
      setUploadedFiles([])
      setSummary({ total_docs: 0, total_queries: 0, total_active_brands: 0, brands: [] })
      setUploadMessage('All data cleared. Upload fresh files to build the dashboard.')
    } catch (error) {
      console.error('Failed to reset uploads', error)
      setUploadMessage('Reset failed. Please try again.')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="data-vault-page">
      <div className="grid-4 mb-20">
        <div className="stat-card">
          <div className="stat-label">Active Brand</div>
          <div className="stat-value">{selectedBrand.name}</div>
          <div className="stat-change up">Current selection</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Brand Files</div>
          <div className="stat-value">{selectedBrandSummary.files}</div>
          <div className="stat-change up">Current brand total</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">AI Queries</div>
          <div className="stat-value">{selectedBrandSummary.queries}</div>
          <div className="stat-change up">Live brand analytics</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Content Pieces</div>
          <div className="stat-value">{selectedBrandSummary.content}</div>
          <div className="stat-change up">Brand corpus size</div>
        </div>
      </div>

      <div className="grid-2-1" style={{ alignItems: 'start' }}>
        <div className="card">
          <div className="section-hd" style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h2>{selectedBrand.name} Files</h2>
              <p className="small muted">Showing uploads for the active brand only</p>
            </div>
            <input 
              type="text" 
              placeholder="Search files..." 
              value={searchTerm} 
              onChange={e => setSearchTerm(e.target.value)} 
              className="select-box"
              style={{ width: '200px', padding: '6px 12px' }}
            />
          </div>
          <div style={{ display: 'grid', gap: '10px' }}>
            {filteredFiles.length > 0 ? filteredFiles.map((file) => (
              <div className="file-row" key={file.id} style={{ alignItems: 'center', padding: '12px' }}>
                <div className="file-icon" style={{ background: file.type === 'pdf' ? 'var(--coral-bg)' : file.type === 'doc' ? 'var(--blue-bg)' : 'var(--teal-bg)', color: file.type === 'pdf' ? 'var(--coral)' : file.type === 'doc' ? 'var(--blue)' : 'var(--teal)' }}>
                  <i className={file.type === 'pdf' ? 'ti ti-file-type-pdf' : file.type === 'doc' ? 'ti ti-file-type-doc' : 'ti ti-table'} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {renameFileId === file.id ? (
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input 
                        type="text" 
                        value={renameTitle} 
                        onChange={e => setRenameTitle(e.target.value)}
                        className="select-box"
                        style={{ padding: '4px 8px', fontSize: 13 }}
                      />
                      <button className="topbar-btn" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => handleRename(file.id)}>Save</button>
                      <button className="topbar-btn" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => setRenameFileId(null)}>Cancel</button>
                    </div>
                  ) : (
                    <div className="file-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</div>
                  )}
                  <div className="file-meta">
                    <span className="badge" style={{ background: 'var(--brand-glow)', color: 'var(--brand)' }}>
                      {file.brand_key}
                    </span>{' '}
                    <span>{file.folder}</span> • <span style={{ color: 'var(--teal)' }}>Indexed</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <div className="file-size" style={{ marginRight: '8px', fontSize: 12, color: 'var(--muted)' }}>{file.size} bytes</div>
                  <button
                    className="topbar-btn"
                    type="button"
                    style={{ padding: '6px 10px', fontSize: 11 }}
                    onClick={() => handleOpenPreview(file)}
                  >
                    View
                  </button>
                  <button
                    className="topbar-btn"
                    type="button"
                    style={{ padding: '6px 10px', fontSize: 11 }}
                    onClick={() => handleDownload(file)}
                  >
                    Download
                  </button>
                  <button
                    className="topbar-btn"
                    type="button"
                    style={{ padding: '6px 10px', fontSize: 11 }}
                    onClick={() => {
                      setRenameFileId(file.id)
                      setRenameTitle(file.name)
                    }}
                  >
                    Rename
                  </button>
                  <button
                    className="topbar-btn"
                    type="button"
                    style={{ padding: '6px 10px', fontSize: 11, background: 'rgba(240, 80, 80, 0.1)', color: '#f05050' }}
                    onClick={() => handleDeleteFile(file.id)}
                    disabled={refreshing}
                  >
                    Remove
                  </button>
                </div>
              </div>
            )) : (
              <div className="file-row" style={{ justifyContent: 'center', color: 'var(--muted)' }}>
                No files found. Upload a file to see it here.
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div className="card-sm">
            <div className="section-hd mb-12"><h2>Upload Files</h2></div>
            <div style={{ marginBottom: '14px' }}>
              <label className="xsmall muted fw-600" style={{ display: 'block', marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '.05em' }}>
                Brand
              </label>
              <select
                className="select-box w-full"
                value={vaultBrand}
                onChange={(event) => onBrandChange?.(event.target.value)}
              >
                {brands.map((b) => (
                  <option key={b.key} value={b.key}>{b.name}</option>
                ))}
              </select>
              <p className="xsmall muted" style={{ marginTop: 4 }}>
                Files upload to and display from this brand.
              </p>
            </div>
            <div
              className="upload-zone"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                const droppedFile = event.dataTransfer.files?.[0]
                if (droppedFile) {
                  setSelectedFile(droppedFile)
                }
              }}
            >
              <i className="ti ti-cloud-upload" />
              <p><strong>Click to select a file</strong> or drag and drop it here</p>
              <p style={{ fontSize: 11, marginTop: 4 }}>PDF, DOCX, TXT, CSV supported</p>
            </div>
            <input ref={fileInputRef} type="file" style={{ display: 'none' }} onChange={handleFileChange} />
            <div style={{ marginTop: 12, fontSize: 13, color: 'var(--muted)' }}>
              {selectedFile ? selectedFile.name : 'No file selected'}
            </div>
            <button className="topbar-btn" type="button" style={{ width: '100%', justifyContent: 'center', marginTop: '10px' }} onClick={handleUpload} disabled={uploading}>
              <i className="ti ti-database-import" /> {uploading ? 'Uploading…' : 'Upload & Index'}
            </button>
            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>{uploadMessage}</div>
          </div>
          <div className="card-sm">
            <div className="section-hd mb-12"><h2>Indexing Status</h2></div>
            <div style={{ display: 'grid', gap: '8px' }}>
              {stats.map((item) => (
                <div key={item.label} className="flex-center gap-8">
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--teal)' }} />
                  <span className="small">{item.label} — {item.value} docs indexed</span>
                </div>
              ))}
              <div className="sep" />
              <button 
                className="topbar-btn" 
                type="button" 
                style={{ background: 'rgba(240, 80, 80, 0.1)', color: '#f05050', border: '1px solid #f05050', width: '100%', justifyContent: 'center' }}
                onClick={handleReset}
              >
                <i className="ti ti-trash" /> Reset Entire Knowledge Base
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Modal Preview Window */}
      {previewFile && (
        <div style={{
          position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', 
          background: 'rgba(0,0,0,0.8)', zIndex: 1000, display: 'flex', 
          justifyContent: 'center', alignItems: 'center', padding: '40px'
        }}>
          <div className="card" style={{ width: '80%', height: '80%', display: 'flex', flexDirection: 'column', background: '#0d0d0f' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid rgba(255,255,255,0.07)', paddingBottom: '12px' }}>
              <div>
                <h3 style={{ margin: 0 }}>{previewFile.name}</h3>
                <span className="small muted">Type: {previewFile.type} | Size: {previewFile.size} bytes</span>
              </div>
              <button className="topbar-btn" onClick={() => setPreviewFile(null)}>Close Preview</button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', background: '#111115', color: '#e4e4e7',border: '1px solid rgba(255,255,255,0.07)', borderRadius: '8px', padding: '20px', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13 }}>
              {previewLoading ? (
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>Loading preview content...</div>
              ) : (
                previewContent || 'No content preview available.'
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}