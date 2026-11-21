import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { Flags } from '../flags.jsx'
import { useTitle } from '../title.js'

const MODES = [
  ['iac', 'IAC network', 'Keyword and meaning evidence combined in an interactive activation network; related files can surface through shared people, references and matters.'],
  ['hybrid', 'Hybrid', 'A match on either the words or the meaning counts.'],
  ['keyword', 'Keyword', 'Exact words (BM25). Put a phrase in "double quotes" to require it.'],
  ['semantic', 'Semantic', 'Meaning of the query compared with each passage.'],
]
const percent = (p) => (p >= 0.995 ? '>99%' : p < 0.01 ? '<1%' : `${Math.round(p * 100)}%`)

export default function Search() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  // A mode can be picked before there is a query; the address only carries it once there is one.
  const [picked, setPicked] = useState('iac')
  const urlMode = MODES.some((m) => m[0] === params.get('mode')) ? params.get('mode') : null
  const mode = urlMode || (q ? 'iac' : picked)
  const [text, setText] = useState(q)
  useTitle(q ? `${q} – Search` : 'Search')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [judged, setJudged] = useState({})

  useEffect(() => {
    setText(q)
    setJudged({})
    setError(null)
    if (!q) {
      setData(null)
      return
    }
    let stale = false
    setLoading(true)
    setError(null)
    api
      .search(q, mode)
      .then((d) => !stale && setData(d))
      .catch((e) => {
        if (stale) return
        setData(null) // never leave an earlier query's results under the error
        setError(e.message)
      })
      .finally(() => !stale && setLoading(false))
    return () => {
      stale = true
    }
  }, [q, mode])

  const go = (nextQ, nextMode) => {
    setPicked(nextMode)
    setParams(nextQ ? { q: nextQ, mode: nextMode } : {})
  }
  const judge = (hit, relevant) => {
    api
      .feedback({ query: q, doc_id: hit.id, relevant, activation: hit.activation })
      .then(() => setJudged((j) => ({ ...j, [hit.id]: relevant })))
      .catch((e) => setError(e.message))
  }
  const modeInfo = MODES.find((m) => m[0] === mode)

  return (
    <>
      <h1>Search</h1>
      <form
        className="searchbar"
        onSubmit={(e) => {
          e.preventDefault()
          go(text.trim(), mode)
        }}
      >
        <input
          type="search"
          autoFocus
          aria-label="Search the documents"
          placeholder="A name, a reference number, or a description of what you are looking for"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button>Search</button>
      </form>
      <div className="modes" role="tablist">
        {MODES.map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={mode === value}
            className={mode === value ? 'mode active' : 'mode'}
            onClick={() => go(q || text.trim(), value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="muted">{modeInfo[2]}</p>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Searching…</p>}

      {data && !loading && (
        <>
          <p>
            {data.results.length === 0
              ? 'No possible matches.'
              : `${data.results.length} possible match${data.results.length > 1 ? 'es' : ''}.`}{' '}
            <span className="muted">
              Chance that none of these is what you want: {percent(data.p_none)}.
            </span>
          </p>
          <ol className="results">
            {data.results.map((hit) => (
              <li key={hit.id} className="result">
                <div className="prob" title="Estimated probability that this document matches the query">
                  <span className="prob-n">{percent(hit.probability)}</span>
                  <div className="bar">
                    <div className="bar-fill" style={{ width: `${hit.probability * 100}%` }} />
                  </div>
                  <span className="sub">match</span>
                  <span className="sub" title="Probability this is the best match among everything returned">
                    {percent(hit.share)} best
                  </span>
                </div>
                <div className="result-body">
                  <Link className="result-title" to={`/documents/${hit.id}${hit.page ? `?page=${hit.page}` : ''}`}>
                    {hit.title || hit.filename}
                  </Link>
                  <div className="sub">
                    {[hit.doc_type, hit.doc_date, hit.matter, `${hit.page_count} pages`, hit.filename]
                      .filter(Boolean)
                      .join(' · ')}
                  </div>
                  {hit.snippet && (
                    <p className="snippet">
                      {hit.page && <span className="muted">p. {hit.page}: </span>}
                      <Snippet text={hit.snippet} />
                    </p>
                  )}
                  {mode === 'iac' && !hit.matched_text && hit.why.some((w) => w.kind !== 'semantic') && (
                    <p className="notice">Does not contain the search words — reached through linked information.</p>
                  )}
                  {hit.why.length > 0 && (
                    <div className="chips">
                      {hit.why.map((w, i) => (
                        <span key={i} className={w.in_query ? 'chip chip-query' : 'chip'} title={`net input ${w.input}`}>
                          <span className="chip-kind">{w.kind}</span> {w.label}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="scores">
                    {hit.activation != null && <span>activation {hit.activation.toFixed(2)}</span>}
                    {hit.keyword_score != null && <span>keyword {hit.keyword_score.toFixed(1)}</span>}
                    {hit.semantic_score != null && <span>similarity {hit.semantic_score.toFixed(2)}</span>}
                    <Flags flags={hit.flags.filter((f) => f.startsWith('pii') || f.startsWith('sensitive'))} />
                    <span className="judge">
                      {judged[hit.id] === undefined ? (
                        <>
                          Is this a match?{' '}
                          <button className="link" onClick={() => judge(hit, true)}>Yes</button>{' '}
                          <button className="link" onClick={() => judge(hit, false)}>No</button>
                        </>
                      ) : (
                        `Recorded: ${judged[hit.id] ? 'match' : 'not a match'}`
                      )}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ol>

          <section className="card">
            <h2>About these probabilities</h2>
            <p>
              <strong>Match</strong> estimates how likely each document is to be relevant on its own.{' '}
              <strong>Best</strong> shares 100% between the documents returned and “none of these” (Luce choice rule).
              {mode === 'iac'
                ? data.calibration.fitted
                  ? ` The match scale has been fitted to ${data.calibration.judgements} Yes/No judgements.`
                  : ` The match scale is a default curve over network activation, not yet checked against real judgements (${data.calibration.judgements} of ${data.calibration.needed} needed, with at least 5 of each answer). Answering “Is this a match?” improves it.`
                : ' In this mode they are rule-of-thumb conversions of the raw score, not calibrated probabilities.'}
            </p>
            {data.network && (
              <details>
                <summary>
                  Network state: {data.network.units} units ({data.network.documents} documents), settled in{' '}
                  {data.network.cycles} cycles
                </summary>
                {data.network.unknown_terms.length > 0 && (
                  <p className="muted">Words not found in any document: {data.network.unknown_terms.join(', ')}</p>
                )}
                <table className="units">
                  <thead>
                    <tr>
                      <th>Unit</th>
                      <th>Pool</th>
                      <th>Activation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.network.active_units.map((u, i) => (
                      <tr key={i}>
                        <td>
                          {u.label} {u.in_query && <span className="tag">from query</span>}
                        </td>
                        <td>{u.kind}</td>
                        <td>
                          <div className="bar small">
                            <div className="bar-fill" style={{ width: `${Math.max(0, u.activation) * 100}%` }} />
                          </div>
                          {u.activation.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </section>
        </>
      )}
    </>
  )
}

function Snippet({ text }) {
  return text.split(/(\[\[.*?\]\])/).map((part, i) =>
    part.startsWith('[[') ? <mark key={i}>{part.slice(2, -2)}</mark> : <span key={i}>{part}</span>,
  )
}
