import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import HoneycombCell from '../components/HoneycombCell';

export default function IronDomeView() {
  const [is3D, setIs3D] = useState(true);

  const resources = Array.from({ length: 24 }).map((_, i) => ({
    id: i,
    name: `aws_node_${i}`,
    type: ['EC2', 'RDS', 'S3', 'IAM', 'EKS'][Math.floor(Math.random() * 5)],
    isCollision: i === 12,
    isReflex: i === 4 || i === 8 || i === 19
  }));

  return (
    <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -15 }} transition={{ duration: 0.3 }} className="flex-1 h-full flex flex-col bg-transparent overflow-hidden px-1 py-1 absolute inset-0 w-full">
      <header className="flex justify-between items-center h-[40px] shrink-0 mb-3">
        <h1 className="text-[20px] font-bold tracking-tight text-slate-800 flex items-center gap-3">
          The Iron Dome
        </h1>
        <div className="flex items-center gap-2 bg-white px-4 py-1.5 rounded-full shadow-sm text-[11px] font-bold border border-slate-200 text-blue-600">
           Active Cluster View
        </div>
      </header>

      <div className="flex-1 bg-white/70 backdrop-blur-2xl rounded-[20px] shadow-sm border border-white p-6 overflow-hidden relative flex flex-col" style={{ perspective: "1500px" }}>
        <div className="absolute inset-0 bg-[radial-gradient(#94a3b8_1px,transparent_1px)] [background-size:24px_24px] opacity-20"></div>
        
        <div className="relative z-10 flex flex-col h-full w-full">
           <div className="mb-8 p-3 bg-white border border-slate-200 rounded-xl shadow-[0_2px_10px_rgb(0,0,0,0.03)] w-max text-[11px] font-bold text-slate-600 flex gap-6">
             <span className="flex items-center gap-2"><div className="w-3 h-3 bg-slate-50 border border-slate-300 rounded"></div> Standard Node</span>
             <span className="flex items-center gap-2"><div className="w-3 h-3 bg-blue-100 border border-blue-400 rounded animate-pulse"></div> Parallel Reflex (Remediating)</span>
             <span className="flex items-center gap-2"><div className="w-3 h-3 bg-amber-100 border border-amber-400 rounded"></div> CISO Override</span>
           </div>

           {/* Offset Honeycomb Grid with Base 3D Rotation */}
           <motion.div 
             animate={is3D ? { rotateX: 45, rotateZ: -10, rotateY: -10, scale: 0.85 } : { rotateX: 0, rotateZ: 0, rotateY: 0, scale: 1 }}
             transition={{ duration: 0.8, ease: "easeInOut" }}
             className="flex-1 w-full flex flex-col gap-2 items-center justify-center overflow-visible py-10 origin-center"
             style={{ transformStyle: "preserve-3d" }}
             onClick={() => setIs3D(!is3D)}
           >
             {[0, 1, 2, 3].map(row => (
               <div key={row} className={`flex gap-3 ${row % 2 === 1 ? 'ml-16' : ''}`}>
                 {resources.slice(row * 6, row * 6 + 6).map(res => (
                   <HoneycombCell key={res.id} data={res} is3D={is3D} />
                 ))}
               </div>
             ))}
           </motion.div>
        </div>
      </div>
    </motion.div>
  );
}
