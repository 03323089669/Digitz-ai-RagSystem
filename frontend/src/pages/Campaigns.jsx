import React, { useEffect, useState } from 'react'
import { getCampaigns, createCampaign } from '../api/client.js'

export default function Campaigns({ selectedBrand }) {
  const [campaigns, setCampaigns] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  // Form State
  const [name, setName] = useState('')
  const [objective, setObjective] = useState('Brand Awareness')
  const [targetAudience, setTargetAudience] = useState('')
  const [budget, setBudget] = useState('')
  const [timeline, setTimeline] = useState('')
  const [status, setStatus] = useState('Draft')
  const [error, setError] = useState('')

  const fetchCampaignsList = async () => {
    setLoading(true)
    try {
      const data = await getCampaigns()
      setCampaigns(data.campaigns || [])
    } catch (err) {
      console.error('Failed to fetch campaigns:', err)
    } finally {
      setLoading(false)
      
    }
  }
  



  useEffect(() => {
    fetchCampaignsList()
  }, [])

  // Filter campaigns for the selected brand
  const filtered = campaigns.filter(c => c.brand_key === selectedBrand.key)

  // Calculate statistics for selected brand
  const activeCount = filtered.filter(c => c.status?.toLowerCase() === 'active').length
  const draftCount = filtered.filter(c => c.status?.toLowerCase() === 'draft').length
  const totalBudget = filtered.reduce((sum, c) => sum + (c.budget || 0), 0)

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Campaign name is required.')
      return
    }
    setError('')
    setSaving(true)
    try {
      await createCampaign({
        name: name.trim(),
        brand_key: selectedBrand.key,
        objective: objective.trim(),
        target_audience: targetAudience.trim() || 'General Audience',
        budget: parseFloat(budget) || 0,
        timeline: timeline.trim() || '1 Month',
        status: status
      })
      // Clear and close
      setName('')
      setTargetAudience('')
      setBudget('')
      setTimeline('')
      setStatus('Draft')
      setModalOpen(false)
      // Refresh list
      await fetchCampaignsList()
    } catch (err) {
      console.error(err)
      setError(err.response?.data?.detail || 'Failed to create campaign. Please check fields.')
    } finally {
      setSaving(false)
    }
  }

  const statusColor = (statusText) => {
    const s = statusText?.toLowerCase()
    if (s === 'active') return { bg: 'var(--teal-bg)', text: 'var(--teal)' }
    if (s === 'draft') return { bg: 'var(--amber-bg)', text: 'var(--amber)' }
    if (s === 'completed') return { bg: 'var(--blue-bg)', text: 'var(--blue)' }
    return { bg: 'var(--bg3)', text: 'var(--muted)' }
  }

  return (
    <div className="campaigns-page">
      {/* Stats Cards Row */}
      <div className="grid-3 mb-20">
        <div className="stat-card">
          <div className="stat-label">Active Campaigns</div>
          <div className="stat-value" style={{ color: 'var(--brand)' }}>{activeCount}</div>
          <div className="stat-change" style={{ color: 'var(--muted)' }}>Running campaigns</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Drafts</div>
          <div className="stat-value" style={{ color: 'var(--amber)' }}>{draftCount}</div>
          <div className="stat-change" style={{ color: 'var(--muted)' }}>Awaiting review</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Allocation</div>
          <div className="stat-value" style={{ color: 'var(--teal)' }}>
            ${totalBudget.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="stat-change" style={{ color: 'var(--muted)' }}>Corpus budget</div>
        </div>
      </div>

      {/* Main Card */}
      <div className="card">
        <div className="section-hd" style={{ marginBottom: '20px' }}>
          <div>
            <h2>Campaign Registry</h2>
            <p className="small muted">Manage marketing pipelines for {selectedBrand.name}</p>
          </div>
          <button className="topbar-btn" type="button" onClick={() => setModalOpen(true)}>
            <i className="ti ti-plus" /> New Campaign
          </button>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--muted)' }}>
            <div className="auth-spinner" style={{ margin: '0 auto 16px' }} />
            Loading campaigns workspace...
          </div>
        ) : filtered.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Campaign Name</th>
                <th>Objective</th>
                <th>Target Audience</th>
                <th>Budget</th>
                <th>Timeline</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((campaign) => {
                const sColor = statusColor(campaign.status)
                return (
                  <tr key={campaign.id || campaign.name}>
                    <td className="fw-500">{campaign.name}</td>
                    <td>{campaign.objective}</td>
                    <td>{campaign.target_audience}</td>
                    <td className="fw-600">${(campaign.budget || 0).toLocaleString()}</td>
                    <td>{campaign.timeline}</td>
                    <td>
                      <span className="badge" style={{ background: sColor.bg, color: sColor.text }}>
                        {campaign.status || 'Draft'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--muted)', background: 'var(--bg2)', borderRadius: 'var(--r)', border: '1px dashed var(--border)' }}>
            <i className="ti ti-speakerphone" style={{ fontSize: '32px', color: 'var(--faint)', marginBottom: '12px', display: 'block' }} />
            <h3 style={{ color: 'var(--text)', marginBottom: '6px' }}>No campaigns found</h3>
            <p className="small muted" style={{ maxWidth: '360px', margin: '0 auto 16px' }}>
              Create a structured campaign brief for {selectedBrand.name} to start generating copy and creative strategies.
            </p>
            <button className="topbar-btn" style={{ margin: '0 auto' }} onClick={() => setModalOpen(true)}>
              + Add First Campaign
            </button>
          </div>
        )}
      </div>

      {/* Creation Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--brand-glow)', display: 'flex', alignItems: 'center', justifycontent: 'center', color: 'var(--brand)' }}>
                  <i className="ti ti-speakerphone" />
                </div>
                <h3 style={{ fontSize: 17, fontWeight: 700, color: 'var(--text)', margin: 0 }}>Create New Campaign</h3>
              </div>
              <button type="button" className="icon-btn" onClick={() => setModalOpen(false)} style={{ border: 'none', background: 'var(--bg3)' }}>
                <i className="ti ti-x" />
              </button>
            </div>

            {error && (
              <div style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8, background: 'var(--red-bg)', color: 'var(--red)', fontSize: 12 }}>
                {error}
              </div>
            )}

            <form onSubmit={handleCreate} style={{ display: 'grid', gap: 12 }}>
              <div className="form-group">
                <label className="form-label">Campaign Name *</label>
                <input
                  className="form-input"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ramadan Campaign 2026"
                />
              </div>

              <div className="grid-2" style={{ gap: 12 }}>
                <div className="form-group">
                  <label className="form-label">Objective</label>
                  <select className="select-box w-full" value={objective} onChange={(e) => setObjective(e.target.value)}>
                    <option value="Brand Awareness">Brand Awareness</option>
                    <option value="Lead Generation">Lead Generation</option>
                    <option value="Web Traffic">Web Traffic</option>
                    <option value="Conversions">Conversions</option>
                    <option value="Product Launch">Product Launch</option>
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Status</label>
                  <select className="select-box w-full" value={status} onChange={(e) => setStatus(e.target.value)}>
                    <option value="Draft">Draft</option>
                    <option value="Active">Active</option>
                    <option value="Completed">Completed</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Target Audience</label>
                <input
                  className="form-input"
                  value={targetAudience}
                  onChange={(e) => setTargetAudience(e.target.value)}
                  placeholder="e.g. Young professionals 22-35 in urban centers"
                />
              </div>

              <div className="grid-2" style={{ gap: 12 }}>
                <div className="form-group">
                  <label className="form-label">Budget ($)</label>
                  <input
                    type="number"
                    className="form-input"
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                    placeholder="e.g. 5000"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Timeline</label>
                  <input
                    className="form-input"
                    value={timeline}
                    onChange={(e) => setTimeline(e.target.value)}
                    placeholder="e.g. 3 Months, June-August"
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <button type="button" className="btn-ghost" onClick={() => setModalOpen(false)}>Cancel</button>
                <button type="submit" className="topbar-btn" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Campaign'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
