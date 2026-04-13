import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Lock, Zap, Server, Shield } from 'lucide-react';

export default function HoneycombCell({ data, is3D }) {
  const [hover, setHover] = useState(false);
  
  const getStyle = () => {
    if (data.isCollision) return "border-amber-400 bg-amber-50 text-amber-600 border-b-[6px]";
    if (data.isReflex) return "border-blue-400 bg-blue-50 text-blue-600 animate-pulse border-b-[6px]";
    return "border-slate-300 bg-white hover:border-blue-300 hover:bg-blue-50 text-slate-500 hover:text-blue-500 border-b-[6px]";
  };

  return (
    <motion.div 
      className="relative flex flex-col items-center justify-center cursor-crosshair transition-all"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      whileTap={{ rotateY: 15, scale: 0.95 }}
      transition={{ duration: 0.3, ease: "easeInOut" }}
      style={{ transformStyle: "preserve-3d" }}
    >
      <motion.div 
        whileHover={{ translateZ: is3D ? 30 : 0, translateY: is3D ? -10 : 0 }}
        className={`w-28 h-28 ${getStyle()} transition-all relative flex flex-col items-center justify-center z-10 shadow-[0_15px_30px_rgba(0,0,0,0.08)]`}
        style={{ clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)', transformStyle: "preserve-3d" }}
      >
        {data.isCollision ? (
          <Lock size={18} className="mb-1" />
        ) : data.isReflex ? (
          <Zap size={18} className="mb-1" />
        ) : (
          <Server size={18} className="mb-1" />
        )}
        <span className="text-[10px] font-bold">{data.type}</span>
      </motion.div>

      <AnimatePresence>
        {hover && (
          <motion.div 
            initial={{ opacity: 0, y: 10, translateZ: 80 }}
            animate={{ opacity: 1, y: 0, translateZ: 80 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className={`absolute top-[-60px] left-1/2 -translate-x-1/2 min-w-[200px] bg-white border border-slate-200 rounded-xl shadow-[0_20px_40px_rgba(0,0,0,0.15)] p-3 z-[100] pointer-events-none origin-bottom`}
            style={is3D ? { transform: 'rotateX(-45deg) rotateZ(10deg) rotateY(10deg)' } : { transform: 'none' }}
          >
            <div className="font-mono text-[10px] text-slate-500 mb-1 font-bold">{data.name}</div>
            {data.isCollision ? (
              <div className="text-[11px] font-bold text-amber-600 flex items-start gap-1">
                <Lock size={12} className="shrink-0 mt-0.5" />
                <span><span className="text-slate-600">CISO Override (J-Impact: 0.82)</span></span>
              </div>
            ) : data.isReflex ? (
              <div className="text-[11px] font-bold text-blue-600 flex items-center gap-1">
                <Shield size={12} /> Dissipating Threat...
              </div>
            ) : (
              <div className="text-[11px] font-bold text-blue-500">Sovereign Fixed.</div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
