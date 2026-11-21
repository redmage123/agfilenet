import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { Flags, flagLabel } from '../flags.jsx'
import { useTitle } from '../title.js'

const FILTERS = [
  ['doc_type', 'Type'],
  ['matter', 'Matter'],
  ['flag', 'Check'],
  ['package', 'Package'],
]

export default function Documents() {
  const [params, setParams] = useSearchParams()
  const [facets, setFacets] = useState(null)
  const [docs, setDocs] = useState(null)
  const [error, setError] = useState(null)
  const filters = Object.fromEntries(params.entries())
  const key = params.toString()
  useTitle('Documents')

  useEffect(() => {
    api.facets().then(setFacets).catch((e) => setError(e.message))
  }, [])
  useEffect(() => {
    api.documents(filters).then(setDocs).catch((e) => setError(e.message))
  }, [key])

  const set = (name, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value)
    else next.delete(name)
    setParams(next, { replace: true })
  }

  if (error) return <p className="error">{error}</p>

  return (
    <>
      <h1>Documents</h1>
      <div className="filters">
        <input
          type="search"
          aria-label="Filter by title, file name or matter"
          placeholder="Filter by title, file name or matter"
          value={filters.q || ''}
          onChange={(e) => set('q', e.target.value)}
        />
        {facets &&
          FILTERS.map(([name, label]) => (
            <label key={name}>
              {label}
              <select value={filters[name] || ''} onChange={(e) => set(name, e.target.value)}>
                <option value="">All</option>
                {name === 'doc_type' && <option value="(none)">(not identified)</option>}
                {facets[name].map((f) => (
                  <option key={f.value} value={f.value}>
                    {name === 'flag' ? flagLabel(f.value) : f.value} ({f.count})
                  </option>
                ))}
              </select>
            </label>
          ))}
        {key && (
          <button className="secondary" onClick={() => setParams({}, { replace: true })}>
            Clear
          </button>
        )}
      </div>

      {!docs ? (
        <p className="muted">Loading…</p>
      ) : docs.length === 0 ? (
        <p className="muted">No documents match. If nothing has been ingested yet, start from the Overview page.</p>
      ) : (
        <>
          <p className="muted">{docs.length} documents</p>
          <div className="table-scroll">
          <table className="doc-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Date</th>
                <th>Matter</th>
                <th className="num">Pages</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>
                    <Link to={`/documents/${d.id}`}>{d.title || d.filename}</Link>
                    <div className="sub">
                      {d.filename} <Flags flags={d.flags} />
                    </div>
                  </td>
                  <td>
                    {d.doc_type || <span className="muted">—</span>}
                    {d.decl_doc_type && d.decl_doc_type !== d.doc_type && (
                      <div className="sub">workbook: {d.decl_doc_type}</div>
                    )}
                  </td>
                  <td className="nowrap">{d.doc_date || <span className="muted">—</span>}</td>
                  <td>{d.matter}</td>
                  <td className="num">{d.page_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}
    </>
  )
}
