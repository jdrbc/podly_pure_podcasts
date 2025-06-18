import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { ToastProvider } from './contexts/ToastContext';
import HomePage from './pages/HomePage';
import AudioPlayer from './components/AudioPlayer';
import ToastContainer from './components/ToastContainer';
import './App.css';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AudioPlayerProvider>
          <Router>
            <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
              <header className="bg-white shadow-sm border-b flex-shrink-0">
                <div className="px-2 sm:px-4 lg:px-6">
                  <div className="flex items-center justify-between h-12">
                    <div className="flex items-center">
                      <img 
                        src="/images/logos/logo.webp" 
                        alt="Podly" 
                        className="h-6 w-auto"
                      />
                      <h1 className="ml-2 text-lg font-semibold text-gray-900">
                        Podly
                      </h1>
                    </div>
                  </div>
                </div>
              </header>

              <main className="flex-1 px-2 sm:px-4 lg:px-6 py-4 overflow-auto">
                <Routes>
                  <Route path="/" element={<HomePage />} />
                </Routes>
              </main>
              
              <AudioPlayer />
              <ToastContainer />
            </div>
          </Router>
        </AudioPlayerProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
