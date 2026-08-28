import React, { useEffect, useState } from 'react'
import { generateReport, getReports } from '../api/client.js'

const reportTypes = [
  'Campaign Performance',
  'Brand Health',
  'Content Analysis',
  'Competitor Benchmark',
]

const periods = ['Last 30 days', 'Last Quarter', 'Last 6 Months', 'Year to Date']

export default function Reports({ selectedBrand, brands = [] }) {
  const [brand, setBrand] = useState(selectedBrand.key)
  const [reportType, setReportType] = useState(reportTypes[0])
  const [period, setPeriod] = useState(periods[0])
  const [loading, setLoading] = useState(false)
  const [statusMessage, setStatusMessage] = useState('Create AI-driven summaries and export them as PDF.')
  const [reports, setReports] = useState([])
  const [fetching, setFetching] = useState(true)

  const fetchReportsList = async () => {
    try {
      const data = await getReports()
      setReports(data.reports || [])
    } catch (error) {
      console.error('Failed to fetch reports list:', error)
    } finally {
      setFetching(false)
    }
  }

  useEffect(() => {
    fetchReportsList()
  }, [])

  useEffect(() => {
    if (selectedBrand?.key) {
      setBrand(selectedBrand.key)
    }
  }, [selectedBrand])

  const handleGenerate = async () => {
    setLoading(true)
    setStatusMessage('Generating PDF report via AI Engine...')

    try {
      const pdfBlob = await generateReport({ brand, report_type: reportType, period })
      const filename = `digitz-ai-report-${brand}-${Date.now()}.pdf`
      const url = window.URL.createObjectURL(new Blob([pdfBlob], { type: 'application/pdf' }))
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      setStatusMessage('Report generated and downloaded successfully.')
      await fetchReportsList() // Refresh list
    } catch (error) {
      console.error(error)
      setStatusMessage('Failed to generate report. Ensure database is connected.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="reports-page">
      <div className="card mb-20">
        <div className="section-hd" style={{ marginBottom: '16px' }}>
          <div>
            <h2>Generate AI Report</h2>
            <p className="small muted">Compile brand knowledge into high-fidelity PDF documents</p>
          </div>
        </div>
        <div className="grid-3" style={{ gap: '12px', marginBottom: '16px' }}>
          <div>
            <label className="xsmall muted fw-600" style={{ display: 'block', marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '.05em' }}>
              Target Brand Workspace
            </label>
            <select className="select-box w-full" value={brand} onChange={(event) => setBrand(event.target.value)}>
              {brands.map((b) => (
                <option key={b.key} value={b.key}>
                  {b.name}
                </option>
              ))}
              {brands.length === 0 && <option value="">Select a brand</option>}
            </select>
          </div>
          <div>
            <label className="xsmall muted fw-600" style={{ display: 'block', marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '.05em' }}>
              Report Focus Area
            </label>
            <select className="select-box w-full" value={reportType} onChange={(event) => setReportType(event.target.value)}>
              {reportTypes.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="xsmall muted fw-600" style={{ display: 'block', marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '.05em' }}>
              Reporting Window
            </label>
            <select className="select-box w-full" value={period} onChange={(event) => setPeriod(event.target.value)}>
              {periods.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </div>
        </div>
        <button className="topbar-btn" type="button" onClick={handleGenerate} disabled={loading}>
          {loading ? (
            <>
              <div className="auth-spinner" style={{ width: 14, height: 14, borderThickness: 2, marginRight: 8 }} />
              Compiling...
            </>
          ) : (
            <>
              <i className="ti ti-report-analytics" /> Generate AI Report
            </>
          )}
        </button>
        <div style={{ marginTop: 12, color: 'var(--muted)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <i className="ti ti-info-circle" style={{ color: 'var(--brand)' }} />
          {statusMessage}
        </div>
      </div>

      <div className="card">
        <div className="section-hd" style={{ marginBottom: '16px' }}>
          <div>
            <h2>Recent Reports Log</h2>
            <p className="small muted">Audit of generated exports saved to database</p>
          </div>
        </div>
        {fetching ? (
          <div style={{ textAlign: 'center', padding: '30px', color: 'var(--muted)' }}>
            <div className="auth-spinner" style={{ margin: '0 auto 12px' }} />
            Retrieving documents logs...
          </div>
        ) : reports.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Report File</th>
                <th>Focus Area</th>
                <th>Brand Key</th>
                <th>Window</th>
                <th>Generated At</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => (
                <tr key={report.id || report.file_name}>
                  <td className="fw-500">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <i className="ti ti-file-text" style={{ color: 'var(--red)', fontSize: 15 }} />
                      {report.file_name}
                    </div>
                  </td>
                  <td>{report.report_type}</td>
                  <td>
                    <span className="badge" style={{ background: 'var(--brand-glow)', color: 'var(--brand)' }}>
                      {report.brand_key}
                    </span>
                  </td>
                  <td>{report.period}</td>
                  <td>{report.created_at ? new Date(report.created_at).toLocaleString() : 'Recent'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--muted)' }}>
            <i className="ti ti-file-off" style={{ fontSize: 28, color: 'var(--faint)', marginBottom: 8, display: 'block' }} />
            No reports registered in logs database yet. Click Generate above to create one.
          </div>
        )}
      </div>
    </div>
  )
}
