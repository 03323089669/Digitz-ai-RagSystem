import React, { useState, useEffect } from 'react'
import { getSettings, saveSettings } from '../api/client.js'

const tabs = [
  { id: 'general',       label: 'General',         icon: 'ti-settings' },
  { id: 'ai',            label: 'AI & Models',      icon: 'ti-brain' },
  { id: 'appearance',    label: 'Appearance',       icon: 'ti-palette' },
  { id: 'integrations',  label: 'Integrations',     icon: 'ti-plug' },
  { id: 'security',      label: 'Security',         icon: 'ti-shield-lock' },
  { id: 'notifications', label: 'Notifications',    icon: 'ti-bell' },
]

const defaultSettings = {
  platform_name: 'Digitz AI',
  support_email: 'support@digitz.co',
  max_users: 25,
  session_timeout: 30,
  groq_api_key: '',
  openai_api_key: '',
  ai_model: 'llama3-8b-8192',
  temperature: 0.7,
  max_tokens: 1024,
  chunk_size: 512,
  chunk_overlap: 50,
  rag_top_k: 5,
  enable_rag: true,
  enable_inferred: true,
  slack_webhook: '',
  notion_key: '',
  email_notify_uploads: true,
  email_notify_queries: false,
  require_mfa: false,
  password_policy: 'strong',
  session_logs: true,
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState('general')
  const [settings, setSettings] = useState(defaultSettings)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await getSettings()
        setSettings((prev) => ({ ...prev, ...data }))
      } catch {
        // use defaults silently
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const set = (key, value) => setSettings((prev) => ({ ...prev, [key]: value }))

  const handleSave = async () => {
    setSaving(true)
    try {
      await saveSettings(settings)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      // fail silently for now
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="grid-2" style={{ gap: 24 }}>
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card skeleton" style={{ height: 120 }} />
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
      {/* Sidebar Tabs */}
      <div className="card" style={{ width: 210, padding: '10px 8px', flexShrink: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--faint)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '4px 10px 10px' }}>
          Settings
        </div>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
            style={{ width: '100%', textAlign: 'left' }}
            onClick={() => setActiveTab(tab.id)}
          >
            <i className={`ti ${tab.icon}`} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Save bar */}
        <div className="flex-between">
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
              {tabs.find((t) => t.id === activeTab)?.label}
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 3 }}>
              Configure your Digitz AI platform settings
            </div>
          </div>
          <button
            type="button"
            className="topbar-btn"
            onClick={handleSave}
            disabled={saving}
            style={{ gap: 8, minWidth: 110 }}
          >
            {saving ? (
              <><div style={{ width: 14, height: 14, borderRadius: '50%', border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', animation: 'spin 0.7s linear infinite' }} /> Saving...</>
            ) : saved ? (
              <><i className="ti ti-check" /> Saved!</>
            ) : (
              <><i className="ti ti-device-floppy" /> Save Changes</>
            )}
          </button>
        </div>

        {/* --- GENERAL TAB --- */}
        {activeTab === 'general' && (
          <div className="card" style={{ display: 'grid', gap: 18 }}>
            <div className="section-hd" style={{ marginBottom: 4 }}>
              <i className="ti ti-settings" style={{ color: 'var(--brand)', fontSize: 16 }} />
              <h2>Platform Settings</h2>
            </div>
            <div className="grid-2" style={{ gap: 16 }}>
              <div className="form-group">
                <label className="form-label">Platform Name</label>
                <input className="form-input" value={settings.platform_name} onChange={(e) => set('platform_name', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Support Email</label>
                <input className="form-input" type="email" value={settings.support_email} onChange={(e) => set('support_email', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Max Users</label>
                <input className="form-input" type="number" min={1} max={500} value={settings.max_users} onChange={(e) => set('max_users', Number(e.target.value))} />
              </div>
              <div className="form-group">
                <label className="form-label">Session Timeout (minutes)</label>
                <input className="form-input" type="number" min={5} max={480} value={settings.session_timeout} onChange={(e) => set('session_timeout', Number(e.target.value))} />
              </div>
            </div>
            <div style={{ padding: '14px 16px', borderRadius: 'var(--r)', background: 'var(--teal-bg)', border: '1px solid var(--teal)', display: 'flex', alignItems: 'center', gap: 10 }}>
              <i className="ti ti-info-circle" style={{ color: 'var(--teal)', fontSize: 16 }} />
              <span style={{ fontSize: 12, color: 'var(--teal)' }}>Changes take effect after saving. Session-related changes may require a page reload.</span>
            </div>
          </div>
        )}

        {/* --- AI & MODELS TAB --- */}
        {activeTab === 'ai' && (
          <div className="card" style={{ display: 'grid', gap: 18 }}>
            <div className="section-hd" style={{ marginBottom: 4 }}>
              <i className="ti ti-brain" style={{ color: 'var(--brand)', fontSize: 16 }} />
              <h2>AI Model Configuration</h2>
            </div>

            <div className="grid-2" style={{ gap: 16 }}>
              <div className="form-group">
                <label className="form-label">Groq API Key</label>
                <input className="form-input" type="password" value={settings.groq_api_key} onChange={(e) => set('groq_api_key', e.target.value)} placeholder="gsk_..." />
              </div>
              <div className="form-group">
                <label className="form-label">OpenAI API Key</label>
                <input className="form-input" type="password" value={settings.openai_api_key} onChange={(e) => set('openai_api_key', e.target.value)} placeholder="sk-..." />
              </div>
              <div className="form-group">
                <label className="form-label">Active LLM Model</label>
                <select className="select-box w-full" value={settings.ai_model} onChange={(e) => set('ai_model', e.target.value)}>
                  <option value="openai/gpt-oss-20b">GPT OSS 20B (Groq Fast)</option>
                  <option value="openai/gpt-oss-120b">GPT OSS 120B (Groq Quality)</option>
                  <option value="llama-3.3-70b-versatile">Llama 3.3 70B (Groq)</option>
                  <option value="gpt-4o-mini">GPT-4o Mini (OpenAI)</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Temperature ({settings.temperature})</label>
                <input type="range" min={0} max={1} step={0.05} value={settings.temperature}
                  onChange={(e) => set('temperature', parseFloat(e.target.value))}
                  style={{ width: '100%', accentColor: 'var(--brand)', marginTop: 8 }}
                />
                <div className="flex-between mt-4">
                  <span className="xsmall muted">Precise</span>
                  <span className="xsmall muted">Creative</span>
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Max Tokens</label>
                <input className="form-input" type="number" min={128} max={8192} value={settings.max_tokens} onChange={(e) => set('max_tokens', Number(e.target.value))} />
              </div>
              <div className="form-group">
                <label className="form-label">RAG Top-K Documents</label>
                <input className="form-input" type="number" min={1} max={20} value={settings.rag_top_k} onChange={(e) => set('rag_top_k', Number(e.target.value))} />
              </div>
              <div className="form-group">
                <label className="form-label">Chunk Size (tokens)</label>
                <input className="form-input" type="number" min={64} max={2048} value={settings.chunk_size} onChange={(e) => set('chunk_size', Number(e.target.value))} />
              </div>
              <div className="form-group">
                <label className="form-label">Chunk Overlap</label>
                <input className="form-input" type="number" min={0} max={512} value={settings.chunk_overlap} onChange={(e) => set('chunk_overlap', Number(e.target.value))} />
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 4 }}>
              <div className="flex-between" style={{ padding: '12px 16px', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', background: 'var(--card2)' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Enable RAG (Retrieval-Augmented Generation)</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Use uploaded brand documents to augment AI responses</div>
                </div>
                <button type="button" className={`toggle ${settings.enable_rag ? 'on' : ''}`} onClick={() => set('enable_rag', !settings.enable_rag)} />
              </div>
              <div className="flex-between" style={{ padding: '12px 16px', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', background: 'var(--card2)' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Enable Inferred Answers</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Allow AI to answer from general knowledge when RAG has no result</div>
                </div>
                <button type="button" className={`toggle ${settings.enable_inferred ? 'on' : ''}`} onClick={() => set('enable_inferred', !settings.enable_inferred)} />
              </div>
            </div>
          </div>
        )}

        {/* --- APPEARANCE TAB --- */}
        {activeTab === 'appearance' && (
          <div className="card" style={{ display: 'grid', gap: 18 }}>
            <div className="section-hd" style={{ marginBottom: 4 }}>
              <i className="ti ti-palette" style={{ color: 'var(--brand)', fontSize: 16 }} />
              <h2>Theme & Appearance</h2>
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              {[
                { value: 'dark',   label: 'Dark Mode',   desc: 'Deep dark, professional UI',           icon: 'ti-moon-stars', preview: '#111115' },
                { value: 'light',  label: 'Light Mode',  desc: 'Clean white modern SaaS look',         icon: 'ti-sun',        preview: '#f4f6fb' },
                { value: 'black',  label: 'Black Mode',  desc: 'Pure black cinematic premium UI',      icon: 'ti-circle-filled', preview: '#000000' },
                { value: 'system', label: 'System',      desc: 'Follow your OS preference',            icon: 'ti-device-desktop', preview: 'linear-gradient(135deg,#111115 50%,#f4f6fb 50%)' },
              ].map((opt) => {
                const isColor = !opt.preview.startsWith('linear')
                return (
                  <div
                    key={opt.value}
                    onClick={() => {}}
                    style={{
                      padding: '14px 16px',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--r-sm)',
                      background: 'var(--card2)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 14,
                      cursor: 'default',
                    }}
                  >
                    <div style={{
                      width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                      background: isColor ? opt.preview : opt.preview,
                      border: '2px solid var(--border2)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <i className={`ti ${opt.icon}`} style={{ fontSize: 16, color: isColor && opt.preview !== '#000000' && opt.preview !== '#111115' ? '#111' : '#fff' }} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{opt.label}</div>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{opt.desc}</div>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                      Use the <i className="ti ti-moon-stars" style={{ fontSize: 13 }} /> menu in the top bar to switch themes.
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* --- INTEGRATIONS TAB --- */}
        {activeTab === 'integrations' && (
          <div className="card" style={{ display: 'grid', gap: 18 }}>
            <div className="section-hd" style={{ marginBottom: 4 }}>
              <i className="ti ti-plug" style={{ color: 'var(--brand)', fontSize: 16 }} />
              <h2>API Integrations</h2>
            </div>
            <div className="grid-2" style={{ gap: 16 }}>
              <div className="form-group">
                <label className="form-label">Slack Webhook URL</label>
                <input className="form-input" value={settings.slack_webhook} onChange={(e) => set('slack_webhook', e.target.value)} placeholder="https://hooks.slack.com/..." />
              </div>
              <div className="form-group">
                <label className="form-label">Notion Integration Key</label>
                <input className="form-input" type="password" value={settings.notion_key} onChange={(e) => set('notion_key', e.target.value)} placeholder="secret_..." />
              </div>
            </div>
            <div style={{ padding: '14px 16px', borderRadius: 'var(--r)', background: 'var(--amber-bg)', border: '1px solid var(--amber)', display: 'flex', alignItems: 'center', gap: 10 }}>
              <i className="ti ti-alert-triangle" style={{ color: 'var(--amber)', fontSize: 16 }} />
              <span style={{ fontSize: 12, color: 'var(--amber)' }}>Keep your API keys secure. Never share them publicly or commit to version control.</span>
            </div>
          </div>
        )}

        {/* --- SECURITY TAB --- */}
        {activeTab === 'security' && (
          <div className="card" style={{ display: 'grid', gap: 18 }}>
            <div className="section-hd" style={{ marginBottom: 4 }}>
              <i className="ti ti-shield-lock" style={{ color: 'var(--brand)', fontSize: 16 }} />
              <h2>Security Settings</h2>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                { key: 'require_mfa',   label: 'Require Multi-Factor Authentication',  desc: 'Enforce 2FA for all admin accounts' },
                { key: 'session_logs',  label: 'Session Audit Logs',                   desc: 'Track all login events and sessions' },
              ].map((item) => (
                <div key={item.key} className="flex-between" style={{ padding: '14px 16px', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', background: 'var(--card2)' }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{item.label}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{item.desc}</div>
                  </div>
                  <button type="button" className={`toggle ${settings[item.key] ? 'on' : ''}`} onClick={() => set(item.key, !settings[item.key])} />
                </div>
              ))}
              <div className="form-group" style={{ marginTop: 8 }}>
                <label className="form-label">Password Policy</label>
                <select className="select-box w-full" value={settings.password_policy} onChange={(e) => set('password_policy', e.target.value)}>
                  <option value="basic">Basic (min 6 chars)</option>
                  <option value="moderate">Moderate (min 8, 1 number)</option>
                  <option value="strong">Strong (min 10, mixed case + symbols)</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {/* --- NOTIFICATIONS TAB --- */}
        {activeTab === 'notifications' && (
          <div className="card" style={{ display: 'grid', gap: 18 }}>
            <div className="section-hd" style={{ marginBottom: 4 }}>
              <i className="ti ti-bell" style={{ color: 'var(--brand)', fontSize: 16 }} />
              <h2>Notification Preferences</h2>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                { key: 'email_notify_uploads', label: 'Email on Document Upload',   desc: 'Get notified when new files are uploaded to any brand' },
                { key: 'email_notify_queries', label: 'Email on AI Query Activity', desc: 'Daily digest of AI queries across all brands' },
              ].map((item) => (
                <div key={item.key} className="flex-between" style={{ padding: '14px 16px', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', background: 'var(--card2)' }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{item.label}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{item.desc}</div>
                  </div>
                  <button type="button" className={`toggle ${settings[item.key] ? 'on' : ''}`} onClick={() => set(item.key, !settings[item.key])} />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
