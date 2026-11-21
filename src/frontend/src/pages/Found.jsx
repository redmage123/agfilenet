import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { flagLabel } from '../flags.jsx'
import { useTitle } from '../title.js'

const fromDocs = (pick) => (db) => db.documents.flatMap(pick)
const ofKind = (kind) => (db) => db.entities.filter((e) => e.kind === kind).map((e) => e.value)

// Every metadata item the app derives from the documents: [name, values found in the database]
const ITEMS = [
  ['Titles', fromDocs((d) => [d.title])],
  ['Document types', fromDocs((d) => [d.doc_type])],
  ['Dates', fromDocs((d) => [d.doc_date])],
  ['Subjects', fromDocs((d) => [d.subject])],
  ['Matters', fromDocs((d) => [d.matter])],
  ['Parties', fromDocs((d) => d.parties.map(([name, role]) => `${name} (${role})`))],
  ['People', ofKind('person')],
  ['Organisations', ofKind('org')],
  ['Places', ofKind('place')],
  ['Court and case numbers', ofKind('case_no')],
  ['File references', ofKind('file_ref')],
  ['Registry volumes', ofKind('registry')],
  ['Topics', fromDocs((d) => [d.topic])],
  ['Checks raised', fromDocs((d) => d.flags.map(flagLabel))],
]
const distinct = (values) =>
  [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
const anchor = (name) => name.toLowerCase().replace(/[^a-z]+/g, '-')

export default function Found() {
  const [db, setDb] = useState(null)
  const [error, setError] = useState(null)
  useTitle('Metadata found')

  useEffect(() => {
    api.database().then(setDb).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!db) return <p className="muted">Loading…</p>

  const items = ITEMS.map(([name, values]) => [name, distinct(values(db))])

  return (
    <>
      <p className="crumbs">
        <Link to="/database">Database</Link> / Metadata found
      </p>
      <h1>Metadata found in the documents</h1>
      <p className="muted">
        Each kind of metadata the app looks for in the {db.counts.documents} ingested files, and the distinct values it
        found. Nothing else is shown here; the <Link to="/database">Database</Link> page has the full records.
      </p>
      <section className="card">
        <h2>Metadata items</h2>
        <ul className="found">
          {items.map(([name, values]) => (
            <li key={name}>
              <a href={`#${anchor(name)}`}>{name}</a> ({values.length})
            </li>
          ))}
        </ul>
      </section>
      {items.map(([name, values]) => (
        <section key={name} className="card" id={anchor(name)}>
          <h2>
            {name} <span className="tag">{values.length}</span>
          </h2>
          {values.length ? (
            <ul className="found">
              {values.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">None found.</p>
          )}
        </section>
      ))}
    </>
  )
}
