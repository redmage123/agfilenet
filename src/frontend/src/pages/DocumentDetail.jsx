import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, pageImage, sourceFile } from '../api.js'
import { Flags } from '../flags.jsx'

const FIELDS = [
  ['title', 'Title'],
  ['doc_type', 'Type'],
  ['doc_date', 'Date (YYYY-MM-DD)'],
  ['subject', 'Subject'],
  ['matter', 'Matter'],
]
const KIND_LABELS = {
  person: 'People',
  org: 'Organisations',
  case_no: 'Court and case numbers',
  file_ref: 'File references',
  registry: 'Registry volumes',
}

export default function DocumentDetail() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const [doc, setDoc] = useState(null)
  const [form, setForm] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showText, setShowText] = useState(true)
  const pageNo = Math.max(1, parseInt(params.get('page') || '1', 10))

  const accept = (d) => {
    setDoc(d)
    setForm(Object.fromEntries(FIELDS.map(([k]) => [k, d[k] || ''])))
  }

  useEffect(() => {
    setDoc(null)
    setError(null)
    api.document(id).then(accept).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="error">{error}</p>
  if (!doc) return <p className="muted">Loading…</p>

  const page = doc.pages[Math.min(pageNo, doc.pages.length) - 1]
  const goto = (n) => setParams({ page: String(n) }, { replace: true })
  const dirty = FIELDS.some(([k]) => (doc[k] || '') !== form[k])
  const save = (e) => {
    e.preventDefault()
    setSaving(true)
    const changes = Object.fromEntries(FIELDS.filter(([k]) => (doc[k] || '') !== form[k]).map(([k]) => [k, form[k]]))
    api
      .saveDocument(doc.id, changes)
      .then(accept)
      .catch((err) => setError(err.message))
      .finally(() => setSaving(false))
  }
  const entityGroups = Object.entries(KIND_LABELS)
    .map(([kind, label]) => [label, doc.entities.filter((e) => e.kind === kind)])
    .filter(([, list]) => list.length)

  return (
    <>
      <p className="crumbs">
        <Link to="/documents">Documents</Link> / {doc.filename}
      </p>
      <h1>{doc.title || doc.filename}</h1>
      <p>
        <Flags flags={doc.flags} />
      </p>

      <div className="detail">
        <div className="detail-meta">
          <section className="card">
            <h2>Metadata {doc.edited ? <span className="tag">corrected by hand</span> : null}</h2>
            <form onSubmit={save}>
              {FIELDS.map(([k, label]) => (
                <label key={k} className="field">
                  {label}
                  <input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                </label>
              ))}
              <button disabled={!dirty || saving}>{saving ? 'Saving…' : 'Save corrections'}</button>
            </form>
            {doc.parties.length > 0 && (
              <p>
                <strong>Parties:</strong> {doc.parties.map(([name, role]) => `${name} (${role})`).join('; ')}
              </p>
            )}
            <dl className="facts">
              <dt>Type confidence</dt>
              <dd>{doc.doc_type ? `${Math.round(doc.doc_type_conf * 100)}% of typed pages agree` : 'not identified'}</dd>
              <dt>Text from</dt>
              <dd>
                {doc.text_source === 'text' ? 'PDF text layer' : doc.text_source === 'ocr' ? 'OCR' : 'text layer and OCR'}
                {doc.ocr_conf != null && ` (mean confidence ${Math.round(doc.ocr_conf * 100)}%)`}
              </dd>
              <dt>File</dt>
              <dd>
                <a href={sourceFile(doc.id)} target="_blank" rel="noreferrer">
                  {doc.path}
                </a>{' '}
                — {doc.page_count} pages, {(doc.size / 1024).toFixed(0)} KB
              </dd>
            </dl>
          </section>

          <section className="card">
            <h2>Declared in the workbook</h2>
            {doc.decl_matter ? (
              <dl className="facts">
                <dt>Matter</dt>
                <dd>{doc.decl_matter}</dd>
                <dt>Matter title</dt>
                <dd>{doc.decl_matter_title || '—'}</dd>
                <dt>Reference</dt>
                <dd>{doc.decl_reference || '—'}</dd>
                <dt>Document type</dt>
                <dd>{doc.decl_doc_type || '— (none given)'}</dd>
                <dt>Comments</dt>
                <dd>{doc.decl_comments || '—'}</dd>
              </dl>
            ) : (
              <p className="muted">This file is not listed in a migration workbook.</p>
            )}
          </section>

          {doc.segments.length > 1 && (
            <section className="card">
              <h2>Documents inside this file</h2>
              <ol className="plain">
                {doc.segments.map((s) => (
                  <li key={s.start_page}>
                    <button className="link" onClick={() => goto(s.start_page)}>
                      {s.start_page === s.end_page ? `Page ${s.start_page}` : `Pages ${s.start_page}–${s.end_page}`}
                    </button>{' '}
                    {s.doc_type || 'Unidentified'}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {(doc.same_file.length > 0 || doc.copied_into.length > 0) && (
            <section className="card">
              <h2>Duplicates</h2>
              <ul className="plain">
                {doc.same_file.map((o) => (
                  <li key={o.id}>
                    Identical file: <Link to={`/documents/${o.id}`}>{o.filename}</Link>
                  </li>
                ))}
                {doc.copied_into.map((o) => (
                  <li key={o.id}>
                    {o.pages} page{o.pages > 1 ? 's' : ''} repeated in{' '}
                    <Link to={`/documents/${o.id}`}>{o.title || o.filename}</Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {entityGroups.length > 0 && (
            <section className="card">
              <h2>Found in the text</h2>
              {entityGroups.map(([label, list]) => (
                <div key={label}>
                  <h3>{label}</h3>
                  <div className="chips">
                    {list.map((e) => (
                      <Link key={e.kind + e.value} className="chip" to={`/search?q=${encodeURIComponent(e.value)}`}>
                        {e.value}
                        {e.docs > 1 && <span className="chip-n">{e.docs} files</span>}
                      </Link>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          )}

          {doc.related.length > 0 && (
            <section className="card">
              <h2>Related documents</h2>
              <ul className="plain">
                {doc.related.map((r) => (
                  <li key={r.id}>
                    <Link to={`/documents/${r.id}`}>{r.title || r.filename}</Link>
                    <div className="sub">shares {r.shared.join(', ')}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <div className="detail-pages">
          {page ? (
            <section className="card">
              <div className="pager">
                <button className="secondary" disabled={page.page_no <= 1} onClick={() => goto(page.page_no - 1)}>
                  ‹ Previous
                </button>
                <span>
                  Page {page.page_no} of {doc.pages.length}
                  {page.page_type && <span className="tag">{page.page_type}</span>}
                  {page.rotation ? <span className="tag">was rotated {page.rotation}°</span> : null}
                </span>
                <button
                  className="secondary"
                  disabled={page.page_no >= doc.pages.length}
                  onClick={() => goto(page.page_no + 1)}
                >
                  Next ›
                </button>
              </div>
              {page.dup_doc_id && (
                <p className="notice">
                  Same content as page {page.dup_page_no} of{' '}
                  {page.dup_doc_id === doc.id ? (
                    'this file'
                  ) : (
                    <Link to={`/documents/${page.dup_doc_id}?page=${page.dup_page_no}`}>{page.dup_filename}</Link>
                  )}
                  .
                </p>
              )}
              <label className="toggle">
                <input type="checkbox" checked={showText} onChange={(e) => setShowText(e.target.checked)} /> Show
                extracted text
                {page.source === 'ocr' && page.ocr_conf != null && (
                  <span className="muted"> (OCR confidence {Math.round(page.ocr_conf * 100)}%)</span>
                )}
              </label>
              <div className={showText ? 'page-view split' : 'page-view'}>
                <img src={pageImage(doc.id, page.page_no)} alt={`Page ${page.page_no}`} />
                {showText && <pre>{page.text || '(no text found on this page)'}</pre>}
              </div>
            </section>
          ) : (
            <p className="muted">This file has no readable pages{doc.error ? `: ${doc.error}` : '.'}</p>
          )}
        </div>
      </div>
    </>
  )
}
