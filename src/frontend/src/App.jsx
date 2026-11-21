import { Link, NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import Database from './pages/Database.jsx'
import Found from './pages/Found.jsx'
import Documents from './pages/Documents.jsx'
import DocumentDetail from './pages/DocumentDetail.jsx'
import Search from './pages/Search.jsx'
import { useTitle } from './title.js'

export default function App() {
  return (
    <>
      <header className="topbar">
        <span className="brand">AG FileNet migration workbench</span>
        <nav>
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/database">Database</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:id" element={<DocumentDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/database" element={<Database />} />
          <Route path="/database/found" element={<Found />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  )
}

function NotFound() {
  useTitle('Page not found')
  return (
    <>
      <h1>Page not found</h1>
      <p>
        This address does not exist in the workbench. Go to the <Link to="/">overview</Link> or the{' '}
        <Link to="/documents">document list</Link>.
      </p>
    </>
  )
}
