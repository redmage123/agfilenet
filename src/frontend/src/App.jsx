import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import Documents from './pages/Documents.jsx'
import DocumentDetail from './pages/DocumentDetail.jsx'
import Search from './pages/Search.jsx'

export default function App() {
  return (
    <>
      <header className="topbar">
        <span className="brand">AG FileNet migration workbench</span>
        <nav>
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/search">Search</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:id" element={<DocumentDetail />} />
          <Route path="/search" element={<Search />} />
        </Routes>
      </main>
    </>
  )
}
