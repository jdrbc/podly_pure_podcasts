import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import HomePage from './pages/HomePage';
import JobsPage from './pages/JobsPage';
import ConfigPage from './pages/ConfigPage';
import LoginPage from './pages/LoginPage';
import AudioPlayer from './components/AudioPlayer';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 0,
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
      refetchOnReconnect: 'always',
    },
  },
});

function AppShell() {
  const { status, requireAuth, isAuthenticated, user, logout } = useAuth();

  if (status === 'loading') {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
          <p className="text-sm text-gray-600">Loading authentication…</p>
        </div>
      </div>
    );
  }

  if (requireAuth && !isAuthenticated) {
    return <LoginPage />;
  }

  const showConfigLink = !requireAuth || user?.role === 'admin';

  return (
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      <header className="bg-white shadow-sm border-b flex-shrink-0">
        <div className="px-2 sm:px-4 lg:px-6">
          <div className="flex items-center justify-between h-12">
            <div className="flex items-center">
              <Link to="/" className="flex items-center">
                <img 
                  src="/images/logos/logo.webp" 
                  alt="Podly" 
                  className="h-6 w-auto"
                />
                <h1 className="ml-2 text-lg font-semibold text-gray-900">
                  Podly
                </h1>
              </Link>
            </div>
            <nav className="flex items-center space-x-4">
              <Link to="/" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                Home
              </Link>
              <Link to="/jobs" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                Jobs
              </Link>
              {showConfigLink && (
                <Link to="/config" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                  Config
                </Link>
              )}
              {requireAuth && user && (
                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <span className="hidden sm:inline">{user.username}</span>
                  <button
                    onClick={logout}
                    className="px-3 py-1 border border-gray-200 rounded-md hover:bg-gray-100 transition-colors"
                  >
                    Logout
                  </button>
                </div>
              )}
            </nav>
          </div>
        </div>
      </header>

      <main className="flex-1 px-2 sm:px-4 lg:px-6 py-4 overflow-auto">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/jobs" element={<JobsPage />} />
          {showConfigLink && <Route path="/config" element={<ConfigPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <AudioPlayer />
      <Toaster position="top-center" toastOptions={{ duration: 3000 }} />
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AudioPlayerProvider>
          <Router>
            <AppShell />
          </Router>
        </AudioPlayerProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
