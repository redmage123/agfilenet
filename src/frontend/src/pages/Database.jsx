import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { flagLabel } from '../flags.jsx'
import { useTitle } from '../title.js'

const KINDS = { person: 'Person', org: 'Organisation', place: 'Place', case_no: 'Case number', file_ref: 'File reference', registry: 'Registry volume' }
const yesNo = (v) => (v ? 'yes' : 'no')
const pct = (v) => (v == null ? null : `${Math.round(v * 100)}%`)
const docLink = (id, text) => <Link to={`/documents/${id}`}>{text}</Link>

// Each view: [key, tab label, rows of the response, columns as [heading, cell(row)]]
const VIEWS = [
  ['documents', 'Documents', (db) => db.documents, [
    ['ID', (d) => d.id],
    ['File', (d) => docLink(d.id, d.filename)],
    ['Path', (d) => d.path],
    ['Package', (d) => d.package],
    ['Folder', (d) => d.folder],
    ['Status', (d) => (d.error ? `${d.status}: ${d.error}` : d.status)],
    ['Title', (d) => d.title],
    ['Type', (d) => d.doc_type],
    ['Type confidence', (d) => pct(d.doc_type_conf)],
    ['Date', (d) => d.doc_date],
    ['Subject', (d) => d.subject],
    ['Topic', (d) => d.topic],
    ['Summary', (d) => d.summary],
    ['Type of similar files', (d) => d.suggested_type],
    ['Matter', (d) => d.matter],
    ['Parties', (d) => d.parties.map(([name, role]) => `${name} (${role})`).join('; ')],
    ['Checks', (d) => d.flags.map(flagLabel).join('; ')],
    ['Corrected by hand', (d) => yesNo(d.edited)],
    ['Workbook matter', (d) => d.decl_matter],
    ['Workbook matter title', (d) => d.decl_matter_title],
    ['Workbook reference', (d) => d.decl_reference],
    ['Workbook type', (d) => d.decl_doc_type],
    ['Workbook comments', (d) => d.decl_comments],
    ['Pages', (d) => d.page_count],
    ['Documents inside', (d) => d.segments],
    ['Text passages', (d) => d.chunks],
    ['Names and references', (d) => d.mentions],
    ['Text from', (d) => d.text_source],
    ['OCR confidence', (d) => pct(d.ocr_conf)],
    ['Content type', (d) => d.content_type],
    ['Size (bytes)', (d) => d.size],
    ['SHA-256', (d) => d.sha256],
    ['Ingested', (d) => d.ingested_at],
  ]],
  ['matters', 'Matters', (db) => db.matters, [
    ['Number', (m) => <Link to={`/documents?matter=${encodeURIComponent(m.number)}`}>{m.number}</Link>],
    ['Title', (m) => m.title],
    ['Reference', (m) => m.reference],
    ['Package', (m) => m.package],
    ['Parties', (m) => m.parties.join('; ')],
    ['Files', (m) => m.documents],
  ]],
  ['entities', 'Names and references', (db) => db.entities, [
    ['Kind', (e) => KINDS[e.kind] || e.kind],
    ['Value', (e) => <Link to={`/search?q=${encodeURIComponent(e.value)}`}>{e.value}</Link>],
    ['Also written', (e) => e.aliases.join('; ')],
    ['Files', (e) => e.documents],
    ['Mentions', (e) => e.mentions],
  ]],
  ['judgements', 'Search judgements', (db) => db.judgements, [
    ['Query', (j) => j.query],
    ['Document', (j) => docLink(j.doc_id, j.document)],
    ['Answer', (j) => (j.relevant ? 'match' : 'not a match')],
    ['Activation', (j) => (j.activation == null ? null : j.activation.toFixed(2))],
    ['Recorded', (j) => j.created],
  ]],
  ['jobs', 'Ingest runs', (db) => db.jobs, [
    ['ID', (j) => j.id],
    ['Status', (j) => j.status],
    ['Pages', (j) => `${j.done} of ${j.total}`],
    ['Message', (j) => j.message],
    ['Started', (j) => j.started],
    ['Finished', (j) => j.finished],
  ]],
]
const STORED = [
  ['documents', 'files'], ['pages', 'pages'], ['segments', 'documents inside files'], ['chunks', 'text passages'],
  ['index_terms', 'indexed words'], ['entities', 'names and references'], ['mentions', 'mentions'],
  ['matters', 'matters'], ['judgements', 'search judgements'], ['jobs', 'ingest runs'],
]
const text = (node) =>
  node == null || node === false ? '' : Array.isArray(node) ? node.map(text).join(' ') : typeof node === 'object' ? text(node.props?.children) : String(node)

export default function Database() {
  const [params, setParams] = useSearchParams()
  const [db, setDb] = useState(null)
  const [error, setError] = useState(null)
  const view = VIEWS.find((v) => v[0] === params.get('view')) || VIEWS[0]
  const q = params.get('q') || ''
  useTitle('Database')

  useEffect(() => {
    api.database().then(setDb).catch((e) => setError(e.message))
  }, [])

  const set = (next) => {
    const p = Object.fromEntries(Object.entries({ view: view[0], q, ...next }).filter(([k, v]) => v && !(k === 'view' && v === VIEWS[0][0])))
    setParams(p, { replace: true })
  }

  if (error) return <p className="error">{error}</p>
  if (!db) return <p className="muted">Loading…</p>

  const [key, , rowsOf, columns] = view
  const all = rowsOf(db)
  const needle = q.trim().toLowerCase()
  const rows = needle ? all.filter((r) => columns.some(([, cell]) => text(cell(r)).toLowerCase().includes(needle))) : all

  return (
    <>
      <h1>Database</h1>
      <p className="muted">
        Everything held in the object database <code>{db.file.path}</code> ({(db.file.size / 1048576).toFixed(1)} MB,
        revision {db.file.revision}), apart from the page text and the search index itself.{' '}
        <Link to="/database/found">See just the metadata items found in the documents.</Link>
      </p>
      <section className="tiles">
        {STORED.map(([name, label]) => (
          <div key={name} className="tile">
            <span className="tile-n">{db.counts[name]}</span>
            <span className="tile-label">{label}</span>
          </div>
        ))}
      </section>

      <div className="modes" role="tablist">
        {VIEWS.map(([value, label, list]) => (
          <button
            key={value}
            role="tab"
            aria-selected={key === value}
            className={key === value ? 'mode active' : 'mode'}
            onClick={() => set({ view: value, q: '' })}
          >
            {label} ({list(db).length})
          </button>
        ))}
      </div>
      <div className="filters">
        <input
          type="search"
          aria-label="Filter the rows"
          placeholder="Filter the rows"
          value={q}
          onChange={(e) => set({ q: e.target.value })}
        />
      </div>

      {rows.length === 0 ? (
        <p className="muted">{all.length ? 'No rows match.' : 'Nothing stored yet.'}</p>
      ) : (
        <>
          <p className="muted">
            {rows.length === all.length ? `${all.length} rows` : `${rows.length} of ${all.length} rows`}
          </p>
          <div className="table-scroll">
            <table className="doc-table wide">
              <thead>
                <tr>
                  {columns.map(([heading]) => (
                    <th key={heading} className="nowrap">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    {columns.map(([heading, cell]) => (
                      <td key={heading}>{[null, undefined, ''].includes(cell(r)) ? <span className="muted">—</span> : cell(r)}</td>
                    ))}
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
