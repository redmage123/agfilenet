import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useTitle } from '../title.js'

const POLL_MS = 2000

export default function Ask() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const [text, setText] = useState(q)
  const [asked, setAsked] = useState(null) // the passages found, and where the answer has got to
  const [error, setError] = useState(null)
  useTitle(q ? `${q} – Ask` : 'Ask')

  useEffect(() => {
    setText(q)
    setAsked(null)
    setError(null)
    if (!q) return
    let stale = false
    let timer = null
    const fail = (e) => !stale && setError(e.message)
    // The passages come back at once; the answer is written in the background and collected when ready.
    const collect = (id) =>
      api
        .askResult(id)
        .then((state) => {
          if (stale) return
          setAsked((a) => ({ ...a, ...state }))
          if (state.status === 'thinking') timer = setTimeout(() => collect(id), POLL_MS)
        })
        .catch(fail)
    api
      .ask(q)
      .then((first) => {
        if (stale) return
        setAsked(first)
        if (first.status === 'thinking') timer = setTimeout(() => collect(first.id), POLL_MS)
      })
      .catch(fail)
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [q])

  return (
    <>
      <h1>Ask the files</h1>
      <form
        className="searchbar"
        onSubmit={(e) => {
          e.preventDefault()
          setParams(text.trim() ? { q: text.trim() } : {})
        }}
      >
        <input
          type="search"
          autoFocus
          aria-label="Ask a question about the documents"
          placeholder="A question the documents might answer, such as who acted for the plaintiff"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button>Ask</button>
      </form>
      <p className="muted">
        The app finds the passages most likely to hold the answer, and a small language model running on this server
        writes an answer from them. Nothing leaves this machine.
      </p>

      {error && <p className="error">{error}</p>}
      {q && !asked && !error && <p className="muted">Finding the passages…</p>}

      {asked && (
        <>
          <section className="card answer" aria-live="polite">
            <h2>Answer</h2>
            {asked.status === 'thinking' && (
              <p className="muted">Reading the passages below and writing an answer — this can take up to a minute…</p>
            )}
            {asked.status === 'done' && asked.answer && (
              <>
                <p className="answer-text">{asked.answer}</p>
                <p className="notice">
                  Written by a small language model. It can misread a passage or state something the passages do not
                  say, so check the answer against the passages below before relying on it. Numbers in [brackets]
                  refer to them.
                </p>
              </>
            )}
            {asked.status === 'done' && !asked.answer && (
              <p className="muted">No passage in the files looks relevant to this question.</p>
            )}
            {asked.status === 'unavailable' && (
              <p className="muted">
                The language model is not installed on this server, so no answer can be written. The passages most
                likely to hold the answer are below.
              </p>
            )}
            {asked.status === 'failed' && (
              <p className="error">The language model could not write an answer. The passages it was given are below.</p>
            )}
          </section>

          {asked.sources.length > 0 && (
            <section className="card">
              <h2>Passages the answer is drawn from</h2>
              <ol className="sources">
                {asked.sources.map((s, i) => (
                  <li key={i}>
                    <Link to={`/documents/${s.id}?page=${s.page}`}>{s.title || s.filename}</Link>
                    <span className="sub">
                      {' '}
                      p. {s.page} · {[s.matter, s.filename].filter(Boolean).join(' · ')}
                    </span>
                    <p className="snippet">{s.text}</p>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </>
  )
}
