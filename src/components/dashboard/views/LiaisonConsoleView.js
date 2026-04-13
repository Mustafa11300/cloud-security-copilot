import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Command, Database, Download } from 'lucide-react';

export default function LiaisonConsoleView() {
  const [jScore, setJScore] = useState(0.852);
  const [timeRemaining, setTimeRemaining] = useState(60);
  const [mode, setMode] = useState('SOVEREIGN');

  // Math visualizer logic
  useEffect(() => {
    const int = setInterval(() => {
      setJScore(prev => prev + (Math.random() * 0.04 - 0.02));
    }, 800);
    return () => clearInterval(int);
  }, []);

  // 60-second execution countdown
  useEffect(() => {
    if (mode !== 'SOVEREIGN') return;
    const ticker = setInterval(() => {
      setTimeRemaining(prev => prev > 0 ? prev - 1 : 60);
    }, 1000);
    return () => clearInterval(ticker);
  }, [mode]);

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} transition={{ duration: 0.4, ease: "easeOut" }} className="flex-1 h-full flex flex-col bg-transparent overflow-hidden px-1 relative absolute inset-0 w-full md:pl-4">
      
      {/* Light Sky Backdrop for Liaison Console */}
      <div className="flex-1 bg-white/60 backdrop-blur-[30px] rounded-[24px] shadow-sm border border-white flex flex-col overflow-hidden relative mb-2 w-full text-slate-800 font-sans">
        
        {/* Header Ribbon */}
        <div className="flex justify-between items-center h-[55px] shrink-0 px-6 border-b border-white bg-white/70 relative z-10">
           <h2 className="text-[15px] font-bold tracking-widest text-blue-600 uppercase flex items-center gap-3">
             <img src="/copilot.png" className="w-7 h-7 object-contain drop-shadow-sm" alt="Copilot Avatar" />
             Liaison Console <span className="text-slate-400 font-bold ml-2 text-[12px]">v4.0.1</span>
           </h2>
           <div className="flex items-center gap-3">
             <div className="px-3 py-1 bg-blue-50 text-blue-600 font-mono font-bold text-[9px] rounded-sm border border-blue-200 shadow-sm uppercase">
               Sys_Link: Stable
             </div>
           </div>
        </div>

        <div className="flex-1 flex flex-col md:flex-row w-full relative z-10 p-6 gap-6 min-h-0">
          
          {/* Main Left Column (Pulse & Interrogator) */}
          <div className="flex-[3] flex flex-col gap-6 w-full min-h-0 h-full">
            
            {/* Component 1: The Narrative Pulse */}
            <div className="flex-1 bg-white/80 border border-white rounded-[20px] p-6 flex flex-col shadow-sm overflow-hidden min-h-0 backdrop-blur-md">
              <h3 className="text-blue-600 font-mono font-bold text-[10px] uppercase tracking-widest mb-6 flex items-center gap-2">
                <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse shadow-[0_0_8px_rgb(59,130,246)]"></div> Explainability Feed
              </h3>
              
              <div className="flex-1 overflow-y-auto scrollbar-hide flex flex-col gap-6 pr-2">
                
                <div className="flex flex-col gap-2">
                  <div className="text-[10px] font-mono text-blue-500 font-bold tracking-widest">[T-04:22:11] KERNEL_DECISION:</div>
                  <div className="text-[13px] text-slate-700 leading-relaxed font-sans font-medium pl-4 border-l-[3px] border-blue-400 rounded-l-sm py-1 bg-gradient-to-r from-blue-50 to-transparent">
                    "I have overridden the Sentry's proposal to force-terminate the EKS Node 'worker-alpha'. While the Sentry identified a High-Risk CVE payload ($W_R: 0.88), the Controller calculated a $14,000/hr operational loss threshold if node capacity drops. I have synthesized a surgical 'Network-Isolation' fix that yields a stable $J$-score of 0.04 without disruption."
                  </div>
                  <div className="flex gap-2 pl-4 mt-2">
                    <span className="text-[9.5px] font-mono font-bold bg-white border border-slate-200 px-3 py-1.5 rounded-lg text-slate-500 hover:bg-blue-50 hover:text-blue-600 hover:border-blue-200 cursor-pointer transition-colors shadow-sm">[NIST-AI-RMF-2.1]</span>
                    <span className="text-[9.5px] font-mono font-bold bg-white border border-slate-200 px-3 py-1.5 rounded-lg text-slate-500 hover:bg-blue-50 hover:text-blue-600 hover:border-blue-200 cursor-pointer transition-colors shadow-sm">[CIS 4.1.2]</span>
                  </div>
                </div>

                <div className="flex flex-col gap-2 opacity-60 hover:opacity-100 transition-opacity">
                  <div className="text-[10px] font-mono text-slate-400 font-bold tracking-widest">[T-14:02:45] KERNEL_DECISION:</div>
                  <div className="text-[13px] text-slate-500 leading-relaxed font-sans font-medium pl-4 border-l-[3px] border-slate-300 py-1">
                    "Executed automated rotation of IAM Access Keys for 'svc-deploy'. Risk delta erased."
                  </div>
                </div>

              </div>
            </div>

            {/* Component 2: The Logic Interrogator */}
            <div className="shrink-0 flex flex-col gap-3">
               <div className="flex gap-2 text-[10px] font-mono font-bold text-blue-600">
                 <div className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white shadow-sm cursor-pointer hover:bg-blue-50 transition-colors uppercase tracking-wider">Show ROI Breakdown</div>
                 <div className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white shadow-sm cursor-pointer hover:bg-blue-50 transition-colors uppercase tracking-wider">Explain w_R Weighting</div>
                 <div className="px-3 py-1.5 rounded-lg border border-blue-200 bg-white shadow-sm cursor-pointer hover:bg-blue-50 transition-colors uppercase tracking-wider">Expand Audit Matrix</div>
               </div>
               
               <div className="w-full bg-white border border-slate-200 rounded-[16px] p-5 flex items-center shadow-sm relative group focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
                  <span className="text-blue-600 font-mono font-bold tracking-widest text-[12px] mr-3 shrink-0 group-focus-within:text-blue-700 transition-colors">sovereign@core:~ $</span>
                  <input type="text" placeholder="_" className="w-full bg-transparent outline-none text-slate-800 font-mono font-bold text-[13px] placeholder:text-slate-400 focus:placeholder:opacity-0" />
                  <Command className="absolute right-5 text-slate-400" size={16} />
               </div>
            </div>
          </div>

          {/* Right Column (J-Eq, Override Bridge, Forensic) */}
          <div className="flex-[2] flex flex-col gap-5 w-full min-h-0 relative z-20">
             
             {/* Component 3: Live J-Equilibrium Breakout */}
             <div className="bg-white/90 backdrop-blur-md border border-white rounded-[20px] p-5 flex flex-col overflow-hidden relative shadow-sm shrink-0">
                <div className="absolute top-0 left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-blue-400 to-transparent opacity-50"></div>
                <h3 className="text-slate-500 font-mono font-bold text-[10px] uppercase tracking-widest mb-4">Live J-Eq Breakout</h3>
                
                <div className="text-center font-mono font-bold text-[12px] text-blue-700 bg-blue-50 py-3 rounded-xl border border-blue-100 mb-6 shadow-inner tracking-widest">
                  J<sub className="text-[8px]">forecast</sub> = min Σ (w<sub className="text-[8px]">R</sub>·P·R<sub className="text-[8px]">i</sub> + w<sub className="text-[8px]">C</sub>·C<sub className="text-[8px]">i</sub>)
                </div>

                <div className="flex flex-col gap-5 relative px-2">
                  <div className="absolute left-[50%] top-0 bottom-0 w-[2px] bg-slate-200 border-dashed z-0"></div>

                  <div className="flex justify-between items-center gap-4 relative z-10 w-full">
                    <span className="font-mono font-bold text-[9px] text-blue-500 uppercase w-20 text-right tracking-wider">Controller</span>
                    <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden flex justify-end p-[2px] border border-slate-200 shadow-inner">
                      <motion.div animate={{ width: ["40%", "80%", "50%"] }} transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }} className="h-full bg-blue-500 rounded-full shadow-[0_0_15px_rgba(59,130,246,0.6)]"></motion.div>
                    </div>
                  </div>

                  <div className="flex justify-between items-center gap-4 relative z-10 w-full">
                    <span className="font-mono font-bold text-[9px] text-indigo-500 uppercase w-20 text-right tracking-wider">Sentry</span>
                    <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden p-[2px] border border-slate-200 shadow-inner">
                      <motion.div animate={{ width: ["70%", "30%", "60%"] }} transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }} className="h-full bg-indigo-500 rounded-full shadow-[0_0_15px_rgba(99,102,241,0.6)]"></motion.div>
                    </div>
                  </div>
                  
                  {/* Glowing Eq Point */}
                  <div className="absolute left-[48%] top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-emerald-400 border-[3px] border-white shadow-[0_0_20px_rgba(52,211,153,0.9)] z-20 flex items-center justify-center"></div>
                </div>
             </div>

             {/* Component 4: Sovereign-to-Pilot Bridge */}
             <div className="bg-white/90 backdrop-blur-md border border-white rounded-[20px] p-5 flex flex-col md:flex-row items-center justify-between shadow-sm relative overflow-hidden gap-4 shrink-0">
                <div className="flex flex-col gap-4 relative z-20">
                  <h3 className="text-slate-500 font-mono font-bold text-[10px] uppercase tracking-widest">Authority Bridge</h3>
                  
                  {/* Mode Toggle */}
                  <div className="flex items-center bg-slate-100 p-1.5 rounded-[12px] border border-slate-200 w-max shadow-inner relative z-10">
                    <button onClick={() => { setMode('SOVEREIGN'); setTimeRemaining(60); }} className={`px-4 py-2 text-[10px] font-bold font-mono tracking-widest rounded-[8px] transition-all uppercase ${mode === 'SOVEREIGN' ? 'bg-blue-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-600 hover:bg-white'}`}>Sovereign</button>
                    <button onClick={() => setMode('PILOT')} className={`px-4 py-2 text-[10px] font-bold font-mono tracking-widest rounded-[8px] transition-all uppercase ${mode === 'PILOT' ? 'bg-amber-500 text-white shadow-md' : 'text-slate-400 hover:text-slate-600 hover:bg-white'}`}>Pilot</button>
                  </div>
                </div>

                {/* Veto Button & Timer */}
                <div className="relative w-24 h-24 flex items-center justify-center shrink-0 mr-4">
                   {/* Background track */}
                   <svg className="absolute inset-0 w-full h-full -rotate-90 block">
                     <circle cx="48" cy="48" r="40" fill="none" stroke="rgba(0,0,0,0.05)" strokeWidth="5" />
                     {mode === 'SOVEREIGN' && (
                       <circle cx="48" cy="48" r="40" fill="none" stroke="#f43f5e" strokeWidth="5" strokeDasharray="251.2" strokeDashoffset={251.2 - (251.2 * timeRemaining) / 60} className="transition-all duration-1000 ease-linear" strokeLinecap="round" />
                     )}
                   </svg>
                   
                   <motion.button 
                     animate={mode === 'SOVEREIGN' ? { scale: 1 - ((60-timeRemaining)/60)*0.25 } : { scale: 1 }}
                     whileHover={mode === 'SOVEREIGN' ? { scale: 0.95 } : {}}
                     whileTap={mode === 'SOVEREIGN' ? { scale: 0.9 } : {}}
                     onClick={() => setMode('PILOT')}
                     className={`w-16 h-16 rounded-full flex flex-col items-center justify-center font-bold tracking-widest text-[11px] uppercase z-10 transition-colors shadow-xl border-4 border-white ${
                       mode === 'SOVEREIGN' ? 'bg-rose-500 text-white hover:bg-rose-600 shadow-[0_10px_25px_rgba(244,63,94,0.4)] cursor-pointer' : 'bg-slate-200 text-slate-400 cursor-not-allowed border-none shadow-none'
                     }`}
                   >
                     Veto
                   </motion.button>
                </div>
             </div>

             {/* Component 5: Re-implemented H-MEM Audit Horizon (Light Theme Version) */}
             <div className="flex-1 bg-white rounded-[20px] p-6 flex flex-col overflow-hidden shadow-sm border border-slate-200 relative">
               <h3 className="text-blue-500 font-mono font-bold text-[9px] uppercase tracking-widest mb-auto flex items-center gap-2">
                 <Database size={12} className="text-blue-600" /> H-MEM Audit Horizon
               </h3>
               
               {/* Timeline graphic reflecting light theme */}
               <div className="w-full relative flex items-center my-8 px-4">
                  {/* Timeline Line */}
                  <div className="w-full h-[1px] bg-slate-200"></div>
                  
                  {/* Left Node */}
                  <div className="absolute left-[20%] top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border border-slate-300 bg-slate-100"></div>
                  
                  {/* Center Node (Active Green) */}
                  <div className="absolute left-[50%] top-1/2 -translate-y-1/2 w-4 h-4 rounded-full border-2 border-emerald-400 bg-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.4)] z-10 pointer-events-none"></div>
                  
                  {/* Right Node */}
                  <div className="absolute left-[80%] top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border border-slate-300 bg-slate-100"></div>
               </div>

               <button className="w-full py-2.5 mt-auto bg-slate-100/50 text-slate-700 hover:bg-blue-50 border border-slate-200 hover:text-blue-600 transition-colors rounded-[8px] text-[9.5px] font-mono font-bold tracking-widest uppercase flex justify-center items-center gap-2">
                 <Download size={14} /> Download Audit Payload
               </button>
             </div>

          </div>
        </div>
      </div>
    </motion.div>
  );
}
