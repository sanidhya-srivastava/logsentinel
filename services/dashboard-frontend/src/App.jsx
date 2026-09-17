import { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';

import Navbar from './components/Navbar';
import LoadingScreen from './components/LoadingScreen';
import Footer from './components/Footer';
import Home from './pages/Home';
import { Features, Workflow as WorkflowPage, Security } from './pages/InfoPages';
import Dashboard from './pages/Dashboard';
import ApiDocs from './pages/ApiDocs';
import OpenConsole from './pages/OpenConsole';

function App() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(false);
    }, 1400);
    return () => clearTimeout(timer);
  }, []);

  return (
    <Router>
      <AnimatePresence mode="wait">
        {loading ? (
          <LoadingScreen key="loading" />
        ) : (
          <motion.div
            key="content"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8 }}
            className="app-shell"
          >
            <div className="app-content">
              <Navbar />
              <main>
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route path="/features" element={<Features />} />
                  <Route path="/workflow" element={<WorkflowPage />} />
                  <Route path="/security" element={<Security />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/api-docs" element={<ApiDocs />} />
                  <Route path="/console" element={<OpenConsole />} />
                </Routes>
              </main>
              <Footer />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Router>
  );
}

export default App;
