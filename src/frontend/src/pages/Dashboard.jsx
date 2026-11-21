import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { flagLabel } from '../flags.jsx'
import { useTitle } from '../title.js'

export default function Dashboard() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [ingestError, setIngestError] = useState(null)
  useTitle('Overview')

  const load = () =>
    api
      .status()
      .then((s) => {
        setStatus(s)
        setError(null)
      })
      .catch((e) => setError(e.message))

  useEffect(() => {
    load()
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [])

  const start = (force) => {
    if (force && !window.confirm('Re-read every file from scratch? OCR of the whole collection can take hours.')) return
    setIngestError(null)
    api.ingest(force).then(load).catch((e) => setIngestError(e.message))
  }

  if (error) return <p className="error">Could not reach the server: {error}</p>
  if (!status) return <p className="muted">Loading…</p>

  const { counts, job, flags } = status
  const busy = job && (job.status === 'running' || job.status === 'queued')
  const percent = job && job.total ? Math.round((100 * job.done) / job.total) : 0

  return (
    <>
      <h1>Overview</h1>
      <p className="muted">
        Source folder <code>{status.data_dir}</code> — {status.files_found} files found, {counts.documents} ingested.
      </p>

      <section className="card">
        <h2>Ingest</h2>
        <p>
          Reads every PDF and image under the source folder, runs OCR on scanned pages, derives metadata and builds
          the search index. Everything runs on this machine. Files already read are skipped.
        </p>
        <div className="row">
          <button onClick={() => start(false)} disabled={busy}>
            {counts.documents ? 'Ingest new or changed files' : 'Start ingest'}
          </button>
          <button className="secondary" onClick={() => start(true)} disabled={busy}>
            Re-read everything
          </button>
          <a className="button secondary" href="/api/export.csv">
            Download metadata (CSV)
          </a>
        </div>
        {ingestError && <p className="error">Could not start the ingest: {ingestError}</p>}
        {job && (
          <div className="job">
            <div className="bar">
              <div className="bar-fill" style={{ width: `${job.status === 'done' ? 100 : percent}%` }} />
            </div>
            <span className={job.status === 'error' ? 'error' : 'muted'}>
              {job.status}: {job.message}
              {busy && job.total ? ` — page ${job.done} of ${job.total}` : ''}
            </span>
          </div>
        )}
      </section>

      <section className="tiles">
        <Tile n={counts.documents} label="files" to="/documents" />
        <Tile n={counts.pages} label="pages" />
        <Tile n={status.duplicate_pages} label="duplicate pages" to="/documents?flag=duplicate-pages" />
        <Tile n={counts.undeclared_type} label="files with no type in the workbook" />
        <Tile n={counts.untyped} label="files the app could not type" to="/documents?doc_type=(none)" />
        <Tile n={status.entities} label="people, bodies and references" />
        <Tile n={counts.edited} label="manually corrected" />
        <Tile n={counts.errors} label="unreadable files" />
      </section>

      <section className="card">
        <h2>Things to check before migration</h2>
        {Object.keys(flags).length === 0 && <p className="muted">Nothing flagged yet.</p>}
        <ul className="flaglist">
          {Object.entries(flags)
            .sort((a, b) => b[1] - a[1])
            .map(([flag, n]) => (
              <li key={flag}>
                <Link to={`/documents?flag=${encodeURIComponent(flag)}`}>
                  <strong>{n}</strong> {flagLabel(flag)}
                </Link>
              </li>
            ))}
        </ul>
      </section>
    </>
  )
}

function Tile({ n, label, to }) {
  const body = (
    <>
      <span className="tile-n">{n}</span>
      <span className="tile-label">{label}</span>
    </>
  )
  return to ? (
    <Link className="tile" to={to}>
      {body}
    </Link>
  ) : (
    <div className="tile">{body}</div>
  )
}
