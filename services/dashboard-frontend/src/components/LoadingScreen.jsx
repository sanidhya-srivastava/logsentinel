import { motion } from 'framer-motion';
import { ShieldCheck } from 'lucide-react';

const LoadingScreen = () => (
  <motion.div
    className="loader"
    initial={{ opacity: 1 }}
    exit={{ opacity: 0, y: -12 }}
    transition={{ duration: 0.45, ease: 'easeInOut' }}
  >
    <div className="loader-card">
      <div className="loader-ring">
        <div className="loader-logo">
          <ShieldCheck size={40} />
        </div>
      </div>
      <p className="loader-title">LogSentinel</p>
      <p className="loader-subtitle">Initializing live observability</p>
      <div className="loader-bar" aria-hidden="true">
        <span />
      </div>
    </div>
  </motion.div>
);

export default LoadingScreen;
