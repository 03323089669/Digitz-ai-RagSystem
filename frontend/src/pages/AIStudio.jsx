import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  queryAI,
  queryAIWithImage,
  getChatSessionMessages,
  renameChatSession,
  setChatSessionFlags,
  deleteChatSession,
  uploadFile,
  getPublicSettings,
  getSettings,
  saveSettings,
} from '../api/client.js'

// ─────────────────────────────────────────────────────────────────────────
// Model picker: maps friendly labels onto the real backend `active_provider`
// values that core/llm_router.py understands. Switching here updates the
// app-wide provider (admin only) via the existing /settings endpoint — there
// is no per-message model override in this backend, so the picker is honest
// about being a global switch, not a per-turn one.
// ─────────────────────────────────────────────────────────────────────────
const MODEL_OPTIONS = [
  { value: 'groq', label: 'GPT OSS 20B (Groq)', icon: 'ti-bolt' },
  { value: 'openai', label: 'GPT-4o mini (OpenAI)', icon: 'ti-brand-openai' },
  { value: 'claude', label: 'Claude (Anthropic)', icon: 'ti-sparkles' },
  { value: 'gemini', label: 'Gemini (Google)', icon: 'ti-brand-google' },
  { value: 'deepseek', label: 'DeepSeek', icon: 'ti-search' },
]

const MODE_TABS = [
  { value: 'Creative', icon: 'ti-pencil' },
  { value: 'Strategy', icon: 'ti-target' },
  { value: 'Report', icon: 'ti-chart-bar' },
  { value: 'Q&A', icon: 'ti-message-question' },
]

const ATTACH_ACCEPT = '.pdf,.doc,.docx,.ppt,.pptx,.csv,.txt'
const IMAGE_ACCEPT = 'image/*'

function timeAgo(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' })
}

function confidenceLabel(score) {
  if (score === undefined || score === null) return null
  if (score >= 0.75) return { label: 'High confidence', tone: 'teal' }
  if (score >= 0.45) return { label: 'Medium confidence', tone: 'amber' }
  return { label: 'Low confidence', tone: 'danger' }
}

function suggestFollowUps(mode, answerText) {
  const base = {
    Creative: ['Give me 3 alternate headlines', 'Turn this into a 5-post content calendar', 'Make the tone more playful'],
    Strategy: ['What are the risks of this approach?', 'How would this compare to last quarter?', 'Turn this into an action plan'],
    Report: ['Summarize this in 3 bullet points', 'Export this as a table', 'What changed since last report?'],
    'Q&A': ['Can you explain that in more detail?', 'What sources back this up?', 'Ask a related question'],
  }
  const pool = base[mode] || base['Q&A']
  if (/table/i.test(answerText || '')) pool.push('Reformat that as bullet points instead')
  return pool.slice(0, 3)
}

// ─── Markdown renderer: tables, code blocks (with copy), lists, headings ──
function CodeBlock({ inline, children, ...props }) {
  const [copied, setCopied] = useState(false)
  if (inline) {
    return <code className="wc-inline-code" {...props}>{children}</code>
  }
  const text = String(children).replace(/\n$/, '')
  const handleCopy = () => {
    navigator.clipboard?.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="wc-codeblock">
      <button type="button" className="wc-codeblock-copy" onClick={handleCopy}>
        <i className={`ti ${copied ? 'ti-check' : 'ti-copy'}`} /> {copied ? 'Copied' : 'Copy'}
      </button>
      <pre><code {...props}>{text}</code></pre>
    </div>
  )
}

function MessageMarkdown({ text }) {
  return (
    <div className="markdown-body wc-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ node, ...props }) => (
            <div className="wc-table-wrap"><table {...props} /></div>
          ),
          code: ({ node, inline, ...props }) => <CodeBlock inline={inline} {...props} />,
          hr: () => <hr className="wc-hr" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

// ─── A single chat bubble ──────────────────────────────────────────────────
function ChatMessage({ message, isLast, onCopy, onRegenerate, onEditLast, brandColor }) {
  const isUser = message.role === 'user'
  const conf = confidenceLabel(message.similarity)

  return (
    <div className={`wc-msg-row ${isUser ? 'user' : 'assistant'}`}>
      <div className={`wc-avatar ${isUser ? 'user' : 'assistant'}`} style={isUser ? { background: brandColor || 'var(--brand)' } : {}}>
        <i className={`ti ${isUser ? 'ti-user' : 'ti-brain'}`} />
      </div>
      <div className="wc-msg-col">
        <div className="wc-msg-meta">
          <span className="wc-msg-sender">{isUser ? 'You' : 'Digitz AI'}</span>
          {message.inferred ? <span className="wc-pill amber">Inferred</span> : null}
          {message.isError ? <span className="wc-pill danger">Error</span> : null}
          <span className="wc-msg-time">{timeAgo(message.timestamp)}</span>
        </div>

        <div className={`wc-bubble ${isUser ? 'user' : 'assistant'}`}>
          {message.attachmentsMeta && message.attachmentsMeta.length > 0 && (
            <div className="wc-msg-attachments">
              {message.attachmentsMeta.map((a) => (
                <span key={a.name} className="wc-attachment-chip">
                  <i className="ti ti-paperclip" /> {a.name}
                </span>
              ))}
            </div>
          )}

          {isUser ? (
            <div className="wc-user-text">
              {/* Inline image preview for user messages */}
              {message.imageDataUrl && (
                <div className="wc-img-preview-wrap">
                  <img
                    src={message.imageDataUrl}
                    alt={message.imageName || 'attached image'}
                    className="wc-img-preview"
                    style={{
                      maxWidth: '100%',
                      maxHeight: 260,
                      borderRadius: 10,
                      marginBottom: 8,
                      display: 'block',
                      objectFit: 'contain',
                      background: 'rgba(0,0,0,0.1)',
                    }}
                  />
                  {message.imageName && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
                      <i className="ti ti-photo" style={{ marginRight: 4 }} />{message.imageName}
                    </div>
                  )}
                </div>
              )}
              {message.content}
            </div>
          ) : message.pending ? (
            <div className="wc-typing">
              <span /><span /><span />
            </div>
          ) : (
            <MessageMarkdown text={message.streamedContent ?? message.content} />
          )}
        </div>

        {!isUser && !message.pending && (
          <>
            {(message.sources && message.sources.length > 0) && (
              <div className="wc-sources">
                <div className="wc-sources-title"><i className="ti ti-file-text" /> Referenced documents</div>
                <div className="wc-sources-list">
                  {message.sources.map((src, idx) => (
                    <div key={`${src.title}-${idx}`} className="wc-source-card">
                      <div className="wc-source-title">{src.title}</div>
                      {src.snippet ? <div className="wc-source-snippet">{src.snippet}</div> : null}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="wc-msg-actions">
              <button type="button" className="wc-action-btn" onClick={() => onCopy(message.content)} title="Copy response">
                <i className="ti ti-copy" /> Copy
              </button>
              {isLast && (
                <button type="button" className="wc-action-btn" onClick={onRegenerate} title="Regenerate response">
                  <i className="ti ti-refresh" /> Regenerate
                </button>
              )}
              {conf && (
                <span className={`wc-pill ${conf.tone}`}>{conf.label} ({Math.round((message.similarity || 0) * 100)}%)</span>
              )}
              {typeof message.responseTime === 'number' && (
                <span className="wc-msg-time-inline">{message.responseTime.toFixed(2)}s</span>
              )}
            </div>
          </>
        )}

        {isUser && isLast && (
          <div className="wc-msg-actions">
            <button type="button" className="wc-action-btn" onClick={() => onEditLast(message.content)} title="Edit and resend">
              <i className="ti ti-pencil" /> Edit
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function AIStudio({ selectedBrand, onBrandChange, brands = [], onOpenBrandModal, user }) {
  const navigate = useNavigate()
  const { session_id: routeSessionId } = useParams()

  const [sessionId, setSessionId] = useState(routeSessionId || null)
  const [sessionTitle, setSessionTitle] = useState('New Chat')
  const [sessionPinned, setSessionPinned] = useState(false)
  const [titleEditing, setTitleEditing] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')

  const [messages, setMessages] = useState([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [sending, setSending] = useState(false)
  const [stopping, setStopping] = useState(false)

  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState('Creative')
  const [attachments, setAttachments] = useState([]) // {id, file, kind: 'doc'|'image', status}
  const [dragActive, setDragActive] = useState(false)
  const [recording, setRecording] = useState(false)
  const [modelProvider, setModelProvider] = useState('groq')
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false)
  const abortControllerRef = useRef(null)

  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const imageInputRef = useRef(null)
  const recognitionRef = useRef(null)

  const brandLabel = selectedBrand?.key === 'ALL' ? 'ALL BRANDS' : (selectedBrand?.name || 'Brand')
  const isAdmin = user?.role === 'admin'

  // ── Load current global provider so the selector reflects reality ──────
  useEffect(() => {
    getPublicSettings().then((s) => {
      if (s?.active_provider) setModelProvider(s.active_provider.toLowerCase())
    }).catch(() => {})
  }, [])

  // ── Load an existing session from the URL, or reset for a new chat ─────
  useEffect(() => {
    let cancelled = false
    setSessionId(routeSessionId || null)

    if (!routeSessionId) {
      setMessages([])
      setSessionTitle('New Chat')
      setSessionPinned(false)
      return
    }

    setLoadingHistory(true)
    getChatSessionMessages(routeSessionId)
      .then((rows) => {
        if (cancelled) return
        const flat = []
        rows.forEach((m, idx) => {
          if (m.question) {
            flat.push({
              id: `${m.id || idx}-q`,
              role: 'user',
              content: m.question,
              timestamp: m.timestamp,
            })
          }
          if (m.answer) {
            let sources = []
            try {
              const raw = m.sources || m.retrieved_documents
              sources = raw ? JSON.parse(raw) : []
            } catch { sources = [] }
            flat.push({
              id: `${m.id || idx}-a`,
              role: 'assistant',
              content: m.answer,
              timestamp: m.timestamp,
              sources,
              responseTime: m.response_time,
            })
          }
        })
        setMessages(flat)
      })
      .catch((e) => console.error('Failed to load chat history', e))
      .finally(() => { if (!cancelled) setLoadingHistory(false) })

    return () => { cancelled = true }
  }, [routeSessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  // Auto-grow textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [prompt])

  const broadcastChatUpdated = () => window.dispatchEvent(new Event('digitz:chat-updated'))



  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setStopping(true)
    setSending(false)
    // Replace pending message with a stopped message
    setMessages((prev) => prev.map((m) =>
      m.pending ? { ...m, pending: false, content: '⚠️ Generation stopped by user.', isError: true, timestamp: new Date().toISOString() } : m
    ))
    broadcastChatUpdated()
  }

  const doSend = async (text, { removeLastPair = false } = {}) => {
    const trimmed = text.trim()
    // Allow sending if there's text OR an image attached
    const imageAttachments = attachments.filter((a) => a.kind === 'image')
    const docAttachments = attachments.filter((a) => a.kind === 'doc')
    if ((!trimmed && imageAttachments.length === 0) || sending) return
    if (!selectedBrand?.key) return

    let baseMessages = messages
    if (removeLastPair) {
      const idx = [...baseMessages].reverse().findIndex((m) => m.role === 'user')
      if (idx !== -1) {
        const cutFrom = baseMessages.length - 1 - idx
        baseMessages = baseMessages.slice(0, cutFrom)
      }
    }

    // Grab the primary image (first one) for vision, rest shown as chips
    const primaryImage = imageAttachments[0] || null
    // Create a local URL for immediate preview (revoked after render on next cycle)
    const imageDataUrl = primaryImage ? URL.createObjectURL(primaryImage.file) : null
    const imageName = primaryImage?.file?.name || null

    const attachmentsMeta = attachments.map((a) => ({ name: a.file.name }))
    const userMsg = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: trimmed || '(Image attached)',
      timestamp: new Date().toISOString(),
      attachmentsMeta,
      imageDataUrl,
      imageName,
    }
    const pendingId = `a-${Date.now()}`
    const pendingMsg = { id: pendingId, role: 'assistant', content: '', pending: true }

    setMessages([...baseMessages, userMsg, pendingMsg])
    setPrompt('')
    setSending(true)
    setStopping(false)

    const pendingAttachments = attachments
    setAttachments([])

    // Create an AbortController for stopping
    abortControllerRef.current = new AbortController()
    const signal = abortControllerRef.current.signal

    try {
      // 1. Upload doc attachments to the knowledge base
      for (const att of docAttachments) {
        try {
          if (signal.aborted) break
          await uploadFile(att.file, selectedBrand.key)
        } catch (e) {
          console.error('Doc upload failed', att.file.name, e)
        }
      }

      if (signal.aborted) return

      // Handle Image + KB path synchronously via existing vision endpoint
      if (primaryImage) {
        const response = await queryAIWithImage(
          trimmed || 'Please analyse this image in the context of our brand.',
          primaryImage.file,
          selectedBrand.key,
          mode,
          sessionId,
        )
        if (signal.aborted) return

        const raw = response.answer || 'Digitz AI did not return a response.'
        
        if (response.session_id && response.session_id !== sessionId) {
          setSessionId(response.session_id)
          navigate(`/chat/${response.session_id}`, { replace: true })
        }
        if (baseMessages.length === 0) {
          setSessionTitle((trimmed || imageName || 'Image query').slice(0, 48))
        }

        const finalMsg = {
          id: pendingId,
          role: 'assistant',
          content: raw,
          sources: response.source_docs || [],
          similarity: response.similarity,
          responseTime: response.response_time,
          timestamp: new Date().toISOString(),
        }
        setMessages((prev) => prev.map((m) => (m.id === pendingId ? finalMsg : m)))
        broadcastChatUpdated()
      } else {
        // SSE Token-by-Token Streaming path for text queries
        const token = localStorage.getItem('digitz-token')
        const apiBase = import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:8000'
        
        const response = await fetch(`${apiBase}/query/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {})
          },
          body: JSON.stringify({
            query: trimmed,
            brand: selectedBrand.key,
            mode: mode,
            session_id: sessionId
          }),
          signal
        })

        if (!response.ok) {
          throw new Error(`Server returned status ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let accumulatedText = ""
        let sources = []
        let eventBuffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (signal.aborted) break
          eventBuffer += decoder.decode(value || new Uint8Array(), { stream: !done })
          const events = eventBuffer.split(/\r?\n\r?\n/)
          eventBuffer = events.pop() || ''

          for (const event of events) {
            const dataLine = event.split(/\r?\n/).find((line) => line.startsWith('data:'))
            if (!dataLine) continue
            const payload = dataLine.slice(5).trim()
            if (payload === '[DONE]') continue

            let data
            try {
              data = JSON.parse(payload)
            } catch (parseError) {
              console.error('Invalid SSE payload from AI backend:', payload, parseError)
              throw new Error('The AI backend returned an invalid response.')
            }

            if (data.type === 'token') {
              accumulatedText += data.token || ''
              setMessages((prev) => prev.map((m) =>
                m.id === pendingId ? { ...m, content: accumulatedText, pending: false } : m
              ))
            } else if (data.type === 'sources') {
              sources = Array.isArray(data.sources) ? data.sources : []
              setMessages((prev) => prev.map((m) =>
                m.id === pendingId ? { ...m, sources } : m
              ))
            } else if (data.type === 'done') {
              const finalContent = data.content ?? data.answer ?? data.response ?? accumulatedText
              if (!String(finalContent || '').trim()) {
                throw new Error('The AI backend returned an empty response.')
              }
              accumulatedText = String(finalContent)
              if (data.session_id && data.session_id !== sessionId) {
                setSessionId(data.session_id)
                navigate(`/chat/${data.session_id}`, { replace: true })
              }
              setMessages((prev) => prev.map((m) =>
                m.id === pendingId ? {
                  ...m,
                  content: accumulatedText,
                  pending: false,
                  sources,
                  responseTime: data.response_time,
                  timestamp: new Date().toISOString()
                } : m
              ))
            } else if (data.type === 'error') {
              throw new Error(data.error || 'The AI provider failed to generate a response.')
            }
          }

          if (done) break
        }

        if (!accumulatedText.trim()) {
          throw new Error('The AI backend returned an empty response.')
        }
        broadcastChatUpdated()
      }
    } catch (error) {
      if (error?.name === 'AbortError' || signal.aborted) return
      console.error('AI query failed:', error)
      const errorMessage = 'Sorry, I couldn\'t generate a response. Please try again.'
      setMessages((prev) => prev.map((m) =>
        m.id === pendingId ? { id: pendingId, role: 'assistant', content: errorMessage, isError: true, timestamp: new Date().toISOString() } : m
      ))
    } finally {
      setSending(false)
      abortControllerRef.current = null
    }
  }

  const handleSend = () => doSend(prompt)

  const handleRegenerate = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    doSend(lastUser.content, { removeLastPair: true })
  }

  const handleEditLast = (content) => {
    setPrompt(content)
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleCopy = (text) => navigator.clipboard?.writeText(text)

  // ── Attachments ──────────────────────────────────────────────────────
  const addFiles = (fileList, kind) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    setAttachments((prev) => [
      ...prev,
      ...files.map((file) => ({ id: `${file.name}-${file.size}-${Date.now()}`, file, kind })),
    ])
  }

  const removeAttachment = (id) => setAttachments((prev) => prev.filter((a) => a.id !== id))

  const handleDrop = (e) => {
    e.preventDefault()
    setDragActive(false)
    const files = Array.from(e.dataTransfer.files || [])
    const images = files.filter((f) => f.type.startsWith('image/'))
    const docs = files.filter((f) => !f.type.startsWith('image/'))
    if (images.length) addFiles(images, 'image')
    if (docs.length) addFiles(docs, 'doc')
  }

  // ── Speech-to-text ───────────────────────────────────────────────────
  const toggleMic = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      alert('Speech recognition is not supported in this browser. Try Chrome or Edge.')
      return
    }
    if (recording) {
      recognitionRef.current?.stop()
      setRecording(false)
      return
    }
    const recognition = new SpeechRecognition()
    recognition.lang = 'en-US'
    recognition.interimResults = false
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((r) => r[0].transcript).join(' ')
      setPrompt((prev) => (prev ? `${prev} ${transcript}` : transcript))
    }
    recognition.onend = () => setRecording(false)
    recognition.onerror = () => setRecording(false)
    recognitionRef.current = recognition
    recognition.start()
    setRecording(true)
  }

  // ── Header actions: rename / pin / delete / export ──────────────────
  const commitTitle = async () => {
    setTitleEditing(false)
    const trimmed = titleDraft.trim()
    if (!trimmed || !sessionId || trimmed === sessionTitle) return
    setSessionTitle(trimmed)
    try {
      await renameChatSession(sessionId, trimmed)
      broadcastChatUpdated()
    } catch (e) { console.error(e) }
  }

  const togglePin = async () => {
    if (!sessionId) return
    const next = !sessionPinned
    setSessionPinned(next)
    try {
      await setChatSessionFlags(sessionId, { isPinned: next })
      broadcastChatUpdated()
    } catch (e) { console.error(e) }
  }

  const handleDeleteSession = async () => {
    if (!sessionId) return
    if (!window.confirm('Delete this chat permanently?')) return
    try {
      await deleteChatSession(sessionId)
      broadcastChatUpdated()
      navigate('/studio')
    } catch (e) { console.error(e) }
  }

  const handleExport = () => {
    const lines = [`# ${sessionTitle}`, `Brand: ${brandLabel}`, `Exported: ${new Date().toISOString()}`, '']
    messages.forEach((m) => {
      lines.push(`**${m.role === 'user' ? 'You' : 'Digitz AI'}** (${timeAgo(m.timestamp)}):`)
      lines.push(m.content)
      lines.push('')
    })
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(sessionTitle || 'chat').replace(/[^a-z0-9-_]+/gi, '_')}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleModelSelect = async (value) => {
    setModelMenuOpen(false)
    if (value === modelProvider) return
    if (!isAdmin) {
      alert('Only administrators can switch the active AI provider (this is an app-wide setting under Settings → AI Provider).')
      return
    }
    try {
      // Preserve existing provider API keys — merge rather than overwrite.
      const current = await getSettings()
      await saveSettings({ ...current, active_provider: value })
      setModelProvider(value)
    } catch (e) {
      console.error('Failed to switch provider', e)
      alert('Could not switch the active AI provider. You can also change it from the Settings page.')
    }
  }

  const lastUserId = useMemo(() => {
    const last = [...messages].reverse().find((m) => m.role === 'user')
    return last?.id
  }, [messages])

  const lastAssistantId = useMemo(() => {
    const last = [...messages].reverse().find((m) => m.role === 'assistant' && !m.pending)
    return last?.id
  }, [messages])

  const lastAssistantMsg = messages.find((m) => m.id === lastAssistantId)
  const followUps = lastAssistantMsg ? suggestFollowUps(mode, lastAssistantMsg.content) : []

  const activeModel = MODEL_OPTIONS.find((m) => m.value === modelProvider) || MODEL_OPTIONS[0]

  return (
    <div
      className="wc-page"
      onDragEnter={(e) => { e.preventDefault(); setDragActive(true) }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragActive(false) }}
      onDrop={handleDrop}
    >
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="wc-header">
        <div className="wc-header-left">
          <div className="wc-brand-dot" style={{ background: selectedBrand?.color || 'var(--brand)' }} />
          {titleEditing ? (
            <input
              autoFocus
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => { if (e.key === 'Enter') commitTitle(); if (e.key === 'Escape') setTitleEditing(false) }}
              className="wc-title-input"
            />
          ) : (
            <button
              type="button"
              className="wc-title-btn"
              onClick={() => { if (sessionId) { setTitleDraft(sessionTitle); setTitleEditing(true) } }}
              title={sessionId ? 'Rename chat' : ''}
            >
              {sessionTitle} {sessionId ? <i className="ti ti-pencil" style={{ fontSize: 12, opacity: 0.5 }} /> : null}
            </button>
          )}
          <span className="wc-header-sub">{brandLabel} namespace</span>
        </div>

        <div className="wc-header-right">
          <div className="wc-mode-tabs">
            {MODE_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                className={`wc-mode-tab ${mode === tab.value ? 'active' : ''}`}
                onClick={() => setMode(tab.value)}
              >
                <i className={`ti ${tab.icon}`} /> {tab.value}
              </button>
            ))}
          </div>

          <div className="wc-model-select">
            <button type="button" className="wc-model-btn" onClick={() => setModelMenuOpen((v) => !v)}>
              <i className={`ti ${activeModel.icon}`} /> {activeModel.label} <i className="ti ti-chevron-down" style={{ fontSize: 11 }} />
            </button>
            {modelMenuOpen && (
              <div className="wc-model-menu">
                {MODEL_OPTIONS.map((opt) => (
                  <button key={opt.value} type="button" className={`wc-model-menu-item ${opt.value === modelProvider ? 'active' : ''}`} onClick={() => handleModelSelect(opt.value)}>
                    <i className={`ti ${opt.icon}`} /> {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <select
            className="select-box"
            style={{ width: 170 }}
            value={selectedBrand?.key || ''}
            onChange={(e) => {
              if (e.target.value === 'other') onOpenBrandModal?.('create')
              else { onBrandChange(e.target.value); navigate('/studio') }
            }}
          >
            <option value="ALL">ALL BRANDS</option>
            {brands.map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
            <option value="other">+ Add New Brand</option>
          </select>

          <div className="wc-header-menu-wrap">
            <button type="button" className="wc-icon-btn" onClick={() => setHeaderMenuOpen((v) => !v)} title="Chat options">
              <i className="ti ti-dots-vertical" />
            </button>
            {headerMenuOpen && (
              <div className="wc-model-menu" style={{ right: 0, left: 'auto' }}>
                <button type="button" className="wc-model-menu-item" disabled={!sessionId} onClick={() => { setHeaderMenuOpen(false); togglePin() }}>
                  <i className={sessionPinned ? 'ti ti-pinned-off' : 'ti ti-pin'} /> {sessionPinned ? 'Unpin chat' : 'Pin chat'}
                </button>
                <button type="button" className="wc-model-menu-item" disabled={!messages.length} onClick={() => { setHeaderMenuOpen(false); handleExport() }}>
                  <i className="ti ti-download" /> Export chat
                </button>
                <button type="button" className="wc-model-menu-item danger" disabled={!sessionId} onClick={() => { setHeaderMenuOpen(false); handleDeleteSession() }}>
                  <i className="ti ti-trash" /> Delete chat
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Chat body ────────────────────────────────────────────────── */}
      <div className="wc-body">
        {loadingHistory ? (
          <div className="wc-empty-state"><div className="auth-spinner" /> Loading conversation...</div>
        ) : messages.length === 0 ? (
          <div className="wc-empty-state">
            <div className="wc-empty-icon"><i className="ti ti-sparkles" /></div>
            <h2>Digitz AI — {brandLabel}</h2>
            <p>Ask about your brand's documents, get creative content, strategy, or a report. Attach files or use your voice below.</p>
            <div className="wc-suggestions">
              {['Summarize our latest brand documents', 'Draft 3 Instagram captions for a new launch', 'What are our Q1 performance highlights?', 'Build a content strategy for next month'].map((s) => (
                <button key={s} type="button" className="wc-suggestion-chip" onClick={() => setPrompt(s)}>
                  <i className="ti ti-sparkles" /> {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="wc-messages">
            {messages.map((m) => (
              <ChatMessage
                key={m.id}
                message={m}
                isLast={m.id === lastUserId || m.id === lastAssistantId}
                onCopy={handleCopy}
                onRegenerate={handleRegenerate}
                onEditLast={handleEditLast}
                brandColor={selectedBrand?.color}
              />
            ))}
            {!sending && followUps.length > 0 && (
              <div className="wc-followups">
                {followUps.map((f) => (
                  <button key={f} type="button" className="wc-suggestion-chip small" onClick={() => doSend(f)}>
                    {f}
                  </button>
                ))}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}

        {dragActive && (
          <div className="wc-drop-overlay">
            <div><i className="ti ti-upload" /> Drop files to attach</div>
          </div>
        )}
      </div>

      {/* ── Composer ─────────────────────────────────────────────────── */}
      <div className="wc-composer-wrap">
        {attachments.length > 0 && (
          <div className="wc-attachment-row">
            {attachments.map((a) => (
              a.kind === 'image' ? (
                /* ── Image attachment: thumbnail preview card ── */
                <div key={a.id} className="wc-attachment-chip removable" style={{ padding: '4px 8px 4px 4px', gap: 8 }}>
                  <img
                    src={URL.createObjectURL(a.file)}
                    alt={a.file.name}
                    style={{
                      width: 40, height: 40,
                      objectFit: 'cover',
                      borderRadius: 6,
                      flexShrink: 0,
                      display: 'block',
                    }}
                  />
                  <span style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {a.file.name}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--muted)', flexShrink: 0 }}>
                    {(a.file.size / 1024).toFixed(0)} KB
                  </span>
                  <button type="button" onClick={() => removeAttachment(a.id)} title="Remove">
                    <i className="ti ti-x" />
                  </button>
                </div>
              ) : (
                /* ── Doc attachment: icon chip ── */
                <div key={a.id} className="wc-attachment-chip removable">
                  <i className="ti ti-file-text" />
                  <span>{a.file.name}</span>
                  <button type="button" onClick={() => removeAttachment(a.id)}><i className="ti ti-x" /></button>
                </div>
              )
            ))}
          </div>
        )}

        <div className="wc-composer">
          <input ref={fileInputRef} type="file" multiple accept={ATTACH_ACCEPT} style={{ display: 'none' }} onChange={(e) => { addFiles(e.target.files, 'doc'); e.target.value = '' }} />
          <input ref={imageInputRef} type="file" multiple accept={IMAGE_ACCEPT} style={{ display: 'none' }} onChange={(e) => { addFiles(e.target.files, 'image'); e.target.value = '' }} />

          <button type="button" className="wc-composer-icon" title="Attach file (PDF, DOCX, PPTX, CSV, TXT)" onClick={() => fileInputRef.current?.click()}>
            <i className="ti ti-paperclip" />
          </button>
          <button type="button" className="wc-composer-icon" title="Attach image" onClick={() => imageInputRef.current?.click()}>
            <i className="ti ti-photo" />
          </button>
          <button type="button" className={`wc-composer-icon ${recording ? 'active' : ''}`} title="Voice input" onClick={toggleMic}>
            <i className={`ti ${recording ? 'ti-player-stop-filled' : 'ti-microphone'}`} />
          </button>

          <textarea
            ref={textareaRef}
            className="wc-textarea"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Ask anything about ${brandLabel}'s data... (drag & drop files anywhere)`}
            rows={1}
          />

          {sending ? (
            <button type="button" className="wc-send-btn stop" onClick={handleStopGeneration} title="Stop generation">
              <i className="ti ti-square-filled" />
            </button>
          ) : (
            <button type="button" className="wc-send-btn" onClick={handleSend} disabled={!prompt.trim() && attachments.length === 0}>
              <i className="ti ti-send" />
            </button>
          )}
        </div>
        <div className="wc-composer-hint">Enter to send · Shift+Enter for a new line · Digitz AI can make mistakes, verify important info.</div>
      </div>
    </div>
  )
}
