import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from '@/components/Layout'
import { Spinner } from '@/components/Ui'
import Admin from '@/pages/Admin'
import Dashboard from '@/pages/Dashboard'
import Enzymes from '@/pages/Enzymes'
import External from '@/pages/External'
import Jobs from '@/pages/Jobs'
import Login from '@/pages/Login'
import ProjectView from '@/pages/ProjectView'
import Projects from '@/pages/Projects'
import SequenceWorkbench from '@/pages/SequenceWorkbench'
import ToolBench from '@/pages/ToolBench'
import { useAuth } from '@/store/auth'
import '@/styles/app.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
  },
})

function App() {
  const { status, bootstrap } = useAuth()

  useEffect(() => {
    if (status === 'idle') void bootstrap()
  }, [status, bootstrap])

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="login-wrap">
        <Spinner label="Starting GeneForge…" />
      </div>
    )
  }

  if (status === 'anonymous') {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:projectId" element={<ProjectView />} />
        <Route path="/sequences/:sequenceId" element={<SequenceWorkbench />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/tools" element={<ToolBench />} />
        <Route path="/enzymes" element={<Enzymes />} />
        <Route path="/external" element={<External />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
