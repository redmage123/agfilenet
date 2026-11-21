import React from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'

// A data router (rather than BrowserRouter) so pages can use useBlocker.
const router = createBrowserRouter([{ path: '*', element: <App /> }])

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
