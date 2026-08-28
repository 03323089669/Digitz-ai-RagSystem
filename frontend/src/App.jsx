import { useEffect, useState, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import './App.css'
import Sidebar from './components/Sidebar.jsx'
import Topbar from './components/Topbar.jsx'
import BrandModal from './components/BrandModal.jsx'
import Dashboard from './pages/Dashboard.jsx'
import AIStudio from './pages/AIStudio.jsx'
import Campaigns from './pages/Campaigns.jsx'
import Analytics from './pages/Analytics.jsx'
import DataVault from './pages/DataVault.jsx'
import Reports from './pages/Reports.jsx'
import Settings from './pages/Settings.jsx'
import Users from './pages/Users.jsx'
import Login from './pages/Login.jsx'
import SearchResults from './pages/SearchResults.jsx'
import BrandPage from './pages/BrandPage.jsx'
import QueryLogs from './pages/QueryLogs.jsx'
import VectorDB from './pages/VectorDB.jsx'
import { getUploadSummary, getCompanies, setActiveCompany, createBrand, updateBrand, deleteBrand, getMe } from './api/client.js'

const routeMap = {
  '/': 'Dashboard',
  '/studio': 'AI Studio',
  '/campaigns': 'Campaigns',
  '/analytics': 'Analytics',
  '/vault': 'Data Vault',
  '/reports': 'Reports',
  '/queries': 'Query Logs',
  '/vector-db': 'Vector DB',
  '/settings': 'Settings',
  '/users': 'Users',
  '/search': 'Search',
}



function getActivePage(pathname) {
  if (pathname.startsWith('/brand/')) 
    return 'Brand'
  return routeMap[pathname] ?? 'Dashboard'
}

function Layout({ selectedBrand, activeBrand, brands, onBrandChange, onOpenBrandModal, onThemeChange, theme, onEditBrand, onDeleteBrand, user, onLogout }) {
  const location = useLocation()
  const navigate = useNavigate()
  const activePage = getActivePage(location.pathname)

  useEffect(() => {
    const match = location.pathname.match(/^\/brand\/(.+)$/)
    if (match) {
      const brandKey = match[1]
      if (brandKey !== activeBrand) onBrandChange(brandKey)
    }
  }, [location.pathname, activeBrand, onBrandChange])

  const handleSearch = (query) => {
    if (!query.trim()) return
    navigate(`/search?query=${encodeURIComponent(query)}`)
  }

  return (
    <div className="app-shell">
      <Sidebar
        activeBrand={activeBrand}
        brands={brands}
        onBrandChange={onBrandChange}
        onCreateBrand={() => onOpenBrandModal('create')}
        onEditBrand={onEditBrand}
        onDeleteBrand={onDeleteBrand}
        user={user}
        onLogout={onLogout}
      />
      <div className="main">
        <Topbar
          activePage={activePage}
          activeBrand={selectedBrand?.name || 'Brand'}
          onAskAI={() => navigate('/studio')}
          onSearch={handleSearch}
          onThemeChange={onThemeChange}
          theme={theme}
        />
        <div className="content">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <Outlet />
          </motion.div>
        </div>
      </div>
    </div>
  )
}

// ─── Auth loading screen ────────────────────────────────────────────────────
function AuthLoading() {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#09090b',
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <div className="auth-spinner" style={{ margin: '0 auto 16px' }} />
        <p style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 500 }}>
          Authorizing Digitz AI session...
        </p>
      </div>
    </div>
  )
}

// ─── Protected route wrapper ────────────────────────────────────────────────
function ProtectedLayout({ authenticated, ...layoutProps }) {
  if (!authenticated) return <Navigate to="/login" replace />
  return <Layout {...layoutProps} />
}

// ─── Main App ───────────────────────────────────────────────────────────────
function App() {
  const [activeBrand, setActiveBrand] = useState('')
  const [brands, setBrands] = useState([])
  const [dashboardSummary, setDashboardSummary] = useState({
    total_docs: 0,
    total_queries: 0,
    total_reports: 0,
    total_campaigns: 0,
    total_active_brands: 0,
    brands: [],
    recent_uploads: [],
    query_history: [],
  })

  const [user, setUser] = useState(null)
  const [authenticated, setAuthenticated] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)

  const [theme, setTheme] = useState('system')
  const [brandModalOpen, setBrandModalOpen] = useState(false)
  const [brandModalMode, setBrandModalMode] = useState('create')
  const [brandModalData, setBrandModalData] = useState(null)

  const selectedBrand =
    activeBrand === 'ALL'
      ? { key: 'ALL', name: 'All Available Brands', color: '#7b6ef6', docs: 0, files: 0, queries: 0, content: 0 }
      : brands.find((b) => b.key === activeBrand) ??
        brands[0] ??
        { key: '', name: 'No company selected', color: '#7b6ef6', docs: 0, files: 0, queries: 0, content: 0 }

  const syncTheme = useCallback((nextTheme) => {
    const root = document.documentElement
    root.classList.remove('theme-light', 'theme-dark', 'theme-black')
    if (nextTheme === 'light') root.classList.add('theme-light')
    else if (nextTheme === 'dark') root.classList.add('theme-dark')
    else if (nextTheme === 'black') root.classList.add('theme-black')
    else {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      root.classList.add(prefersDark ? 'theme-dark' : 'theme-light')
    }
    localStorage.setItem('digitz-theme', nextTheme)
    setTheme(nextTheme)
  }, [])

  const refreshData = useCallback(async () => {
    try {
      const [companiesResponse, summaryResponse] = await Promise.all([getCompanies(), getUploadSummary()])
      const mappedBrands = companiesResponse.companies.map((brand) => ({
        ...brand,
        docs: brand.docs ?? 0,
        files: brand.files ?? 0,
        queries: brand.queries ?? 0,
        content: brand.content ?? 0,
        chunks: brand.chunks ?? 0,
        storage: brand.storage ?? 0,
        last_upload: brand.last_upload || '',
      }))
      setBrands(mappedBrands)
      setDashboardSummary(summaryResponse)
      const activeKey = companiesResponse.active_company || mappedBrands[0]?.key || ''
      setActiveBrand((current) => (current || activeKey))
    } catch (error) {
      console.error('Failed to refresh data', error)
    }
  }, [])

  const handleBrandChange = useCallback(async (brandKey) => {
    // Allow "ALL" as a special search scope (not a real brand)
    if (brandKey === 'ALL') {
      setActiveBrand('ALL')
      return
    }
    // For regular brands, check validity
    if (!brandKey || brandKey === activeBrand) return
    setActiveBrand(brandKey)
    try {
      await setActiveCompany(brandKey)
    } catch (error) {
      console.error('Failed to persist active company', error)
    }
  }, [activeBrand])

  const checkAuth = useCallback(async () => {
    const token = localStorage.getItem('digitz-token')
    if (!token) {
      setUser(null)
      setAuthenticated(false)
      setAuthLoading(false)
      return
    }
    try {
      const data = await getMe()
      setUser(data.user)
      setAuthenticated(true)
    } catch {
      setUser(null)
      setAuthenticated(false)
    } finally {
      setAuthLoading(false)
    }
  }, [])

  useEffect(() => {
    const savedTheme = localStorage.getItem('digitz-theme') || 'system'
    syncTheme(savedTheme)
    checkAuth()
  }, [syncTheme, checkAuth])

  useEffect(() => {
    if (!authenticated) return
    refreshData()
    const interval = setInterval(refreshData, 12000)
    return () => clearInterval(interval)
  }, [authenticated, refreshData])

  useEffect(() => {
    if (!brands.length) return
    // "ALL" is a valid special value that doesn't need to exist in brands list
    if (activeBrand === 'ALL') return
    const exists = brands.some((b) => b.key === activeBrand)
    if (!exists) setActiveBrand(brands[0]?.key ?? '')
  }, [brands, activeBrand])

  const openBrandModal = (mode, brand = null) => {
    setBrandModalMode(mode)
    setBrandModalData(brand)
    setBrandModalOpen(true)
  }

  const closeBrandModal = () => {
    setBrandModalOpen(false)
    setBrandModalData(null)
  }

  const handleSaveBrand = async (payload) => {
    try {
      if (brandModalMode === 'edit' && brandModalData) {
        await updateBrand(brandModalData.key, payload)
      } else {
        await createBrand(payload)
        await setActiveCompany(payload.key)
        setActiveBrand(payload.key)
      }
      closeBrandModal()
      await refreshData()
    } catch (error) {
      console.error('Failed to save brand', error)
    }
  }

  const handleDeleteBrand = async (brandKey) => {
    if (!window.confirm(`Are you sure you want to delete brand '${brandKey}' and all its linked documents, conversations, and campaign statistics?`)) return
    try {
      await deleteBrand(brandKey)
      if (brandKey === activeBrand) setActiveBrand(brands[0]?.key ?? '')
      await refreshData()
    } catch (error) {
      console.error('Failed to delete brand', error)
    }
  }

  const handleEditBrand = (brand) => openBrandModal('edit', brand)

  const handleLoginSuccess = async () => {
    await checkAuth()
    await refreshData()
  }

  const handleLogout = () => {
    localStorage.removeItem('digitz-token')
    setAuthenticated(false)
    setUser(null)
  }

  // ── Show auth loading spinner until token check completes ────────────────
  if (authLoading) return <AuthLoading />

  const layoutProps = {
    authenticated,
    selectedBrand,
    activeBrand,
    brands,
    onBrandChange: handleBrandChange,
    onOpenBrandModal: openBrandModal,
    onThemeChange: syncTheme,
    theme,
    onEditBrand: handleEditBrand,
    onDeleteBrand: handleDeleteBrand,
    user,
    onLogout: handleLogout,
  }

  return (
    <BrowserRouter>
      <BrandModal
        open={brandModalOpen}
        onClose={closeBrandModal}
        onSave={handleSaveBrand}
        initialData={brandModalMode === 'edit' ? brandModalData : null}
      />
      <Routes>
        {/* ── Public route: login ─────────────────────────────────────── */}
        <Route
          path="/login"
          element={
            authenticated
              ? <Navigate to="/" replace />
              : <Login onLoginSuccess={handleLoginSuccess} />
          }
        />

        {/* ── Protected routes ────────────────────────────────────────── */}
        <Route element={<ProtectedLayout {...layoutProps} />}>
          <Route index element={<Dashboard selectedBrand={selectedBrand} summary={dashboardSummary} onEditBrand={handleEditBrand} onDeleteBrand={handleDeleteBrand} />} />
          <Route path="studio" element={<AIStudio selectedBrand={selectedBrand} onBrandChange={setActiveBrand} brands={brands} onOpenBrandModal={openBrandModal} user={user} />} />
          <Route path="campaigns" element={<Campaigns selectedBrand={selectedBrand} brands={brands} />} />
          <Route path="analytics" element={<Analytics selectedBrand={selectedBrand} />} />
          <Route path="vault" element={<DataVault selectedBrand={selectedBrand} onRefreshSummary={refreshData} brands={brands} onBrandChange={setActiveBrand} />} />
          <Route path="reports" element={<Reports selectedBrand={selectedBrand} brands={brands} />} />
          <Route path="queries" element={<QueryLogs selectedBrand={selectedBrand} />} />
          <Route path="vector-db" element={<VectorDB selectedBrand={selectedBrand} />} />
          <Route path="settings" element={<Settings selectedBrand={selectedBrand} />} />
          <Route path="users" element={<Users selectedBrand={selectedBrand} />} />
          <Route path="search" element={<SearchResults selectedBrand={selectedBrand} />} />
          <Route path="brand/:brandKey" element={<BrandPage selectedBrand={selectedBrand} brands={brands} />} />
          <Route path="chat/:session_id" element={<AIStudio selectedBrand={selectedBrand} onBrandChange={setActiveBrand} brands={brands} onOpenBrandModal={openBrandModal} user={user} />} />
        </Route>


        {/* ── Fallback ─────────────────────────────────────────────────── */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
