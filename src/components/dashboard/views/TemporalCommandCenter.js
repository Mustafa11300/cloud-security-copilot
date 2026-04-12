import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Zap, Shield, AlertTriangle, ChevronRight, Database, BookOpen, Activity } from 'lucide-react';
import MetricCard from '../components/MetricCard';
import RiskItem from '../components/RiskItem';
import LogTerminalItem from '../components/LogTerminalItem';

export default function TemporalCommandCenter({ onCopilotClick }) {
  const [activeTab, setActiveTab] = useState('Tick');

  return (
    <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -15 }} transition={{ duration: 0.3 }} className="flex-1 h-full flex gap-4 overflow-hidden w-full absolute inset-0">
      <main className="flex-1 h-full flex flex-col gap-3 overflow-hidden">
        
        <header className="flex justify-between items-center px-1 h-[36px] shrink-0 mb-1">
          <div className="flex items-center gap-3">
            <h1 className="text-[19px] font-bold tracking-tight text-slate-800 flex items-center">
              Overview
            </h1>
          </div>
          <div className="flex items-center gap-3 bg-white/60 backdrop-blur-md rounded-full p-1 shadow-sm border border-white">
            <button className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded-full text-[11px] font-semibold transition-colors shadow-sm ml-0.5">
              <Zap size={12} className="text-white" /> T-Minus Sync
            </button>
          </div>
        </header>

        {/* Top Metric Cards - Strictly Sky / Blue Theme */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 shrink-0">
          <MetricCard 
            title="Posture Score" value="84" suffix="/100"
            badge="AVG. PRE-CRIME LEAD: +2.4 Ticks" badgeColor="text-blue-600 bg-blue-50 font-bold border border-blue-200 tracking-tight"
            progress={84} progressColor="from-blue-400 to-blue-500"
          />
          <MetricCard 
            title="Active Perturbations" value="3" suffix=" Vectors"
            badge="Action Needed" badgeColor="text-blue-600 bg-blue-50 border border-blue-200"
            progress={15} progressColor="from-blue-400 to-blue-500"
          />
          <MetricCard 
            title="Resources Indexed" value="1,492" suffix=""
            badge="Sovereign Active" badgeColor="text-blue-600 bg-blue-50 border border-blue-200"
            hideBar={true}
          />
          <MetricCard 
            title="Fast-Pass Savings" value="$2.4k" suffix="/mo"
            badge="$250 from shadow AI shutdown" badgeColor="text-blue-600 bg-blue-50 border border-blue-200 font-bold"
            progress={40} progressColor="from-blue-400 to-blue-500"
          />
        </div>

        {/* Middle Row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 flex-1 min-h-0">
          
          {/* Horizontal Pulse Stream */}
          <div className="md:col-span-2 bg-white/70 backdrop-blur-xl rounded-[20px] p-4 shadow-sm border border-white flex flex-col h-full overflow-hidden">
             <div className="flex justify-between items-start mb-3 shrink-0">
              <div>
                <h3 className="text-[13px] font-bold text-slate-800">Temporal Risk Horizon</h3>
              </div>
              <div className="flex p-0.5 bg-slate-100/80 rounded-full border border-slate-200">
                {['Tick', 'Epoch', 'Cycle'].map(tab => (
                  <button key={tab} onClick={() => setActiveTab(tab)} className={`px-4 py-1 rounded-full text-[10px] font-bold transition-all ${activeTab === tab ? 'bg-white text-slate-800 shadow-sm border border-slate-200/50' : 'text-slate-500 hover:text-slate-700'}`}>
                    {tab}
                  </button>
                ))}
              </div>
            </div>
            
            <div className="flex-1 w-full min-h-0 relative mt-2 bg-blue-50/50 rounded-[16px] overflow-hidden flex border border-blue-100/50 shadow-inner">
                {/* Left: Past Events */}
                <div className="w-[30%] h-full border-r border-blue-200 border-dashed flex flex-col justify-center items-end pr-6 gap-6 relative">
                    <div className="absolute top-4 right-4 text-[10px] font-bold text-blue-500 uppercase tracking-widest bg-white py-1 px-3 rounded shadow-sm border border-blue-100">Past Events</div>
                    <div className="flex items-center gap-2 opacity-60"><div className="w-4 h-4 rounded-full bg-blue-300"></div><div className="h-0.5 w-16 bg-blue-200"></div></div>
                    <div className="flex items-center gap-2 opacity-40"><div className="w-4 h-4 rounded-full bg-blue-300"></div><div className="h-0.5 w-24 bg-blue-200"></div></div>
                </div>
                
                {/* Center: Present Status */}
                <div className="w-[40%] h-full flex flex-col justify-center items-center relative z-10">
                    <div className="absolute top-4 text-[10px] uppercase font-bold text-blue-600 bg-white border border-blue-100 shadow-sm py-1 px-4 rounded-full">Present Status</div>
                    
                    <div className="flex items-center gap-4">
                      <div className="w-16 h-1 bg-gradient-to-r from-blue-200 to-blue-400 rounded"></div>
                      <motion.div 
                        animate={{ scale: [1, 1.15, 1], boxShadow: ["0px 0px 0px rgba(59,130,246,0)", "0px 0px 20px rgba(59,130,246,0.4)", "0px 0px 0px rgba(59,130,246,0)"] }}
                        transition={{ repeat: Infinity, duration: 2, ease: "easeInOut" }}
                        className="w-16 h-16 bg-white border-[5px] border-blue-400 rounded-full flex items-center justify-center relative z-20 shadow-md"
                      >
                         <Shield className="text-blue-500" size={24} />
                      </motion.div>
                      <div className="w-16 h-1 bg-gradient-to-l from-blue-300/50 to-blue-400 rounded"></div>
                    </div>
                </div>
                
                {/* Right: Forecast Horizon (Sky Themed!) */}
                <div className="w-[30%] h-full bg-gradient-to-r from-blue-50 to-blue-100 flex flex-col justify-center items-start pl-6 gap-4 relative overflow-hidden border-l border-blue-200">
                    <div className="absolute top-4 left-4 text-[10px] uppercase font-bold text-blue-600 flex items-center gap-1.5"><AlertTriangle size={12}/> Forecast Horizon</div>
                    
                    <motion.div 
                      animate={{ x: [50, 0], opacity: [0, 1] }} transition={{ repeat: Infinity, duration: 4, ease: "easeOut" }}
                      className="bg-blue-500 text-white text-[10px] font-bold px-3 py-1.5 rounded-full shadow-[0_4px_15px_rgba(59,130,246,0.4)] flex items-center gap-2"
                    >
                      <div className="w-2 h-2 bg-blue-200 rounded-full animate-pulse"></div> LSTM: Drift Span
                    </motion.div>
                </div>
            </div>
          </div>

          {/* Liaison Console Link Block - Sky Blue Gradient */}
          <motion.div 
             whileHover={{ y: -4 }}
             className="relative overflow-hidden bg-gradient-to-b from-[#7dbbff] to-[#dcedff] rounded-[20px] flex flex-col h-full border border-blue-200 shadow-sm cursor-pointer md:col-span-1 min-h-[300px]" 
             onClick={onCopilotClick}
          >
             <div className="p-4 flex flex-col relative z-20 h-full w-full">
               <h3 className="text-[17px] font-bold text-white mb-0.5 leading-tight drop-shadow-sm">
                 Liaison Console
               </h3>
               <p className="text-[11px] text-blue-900/80 leading-snug font-bold mb-3">
                 Automated remediation online.
               </p>
               
               <div className="flex flex-col gap-2 relative z-20 w-max max-w-full">
                  <div className="bg-white/50 backdrop-blur-md rounded-md px-3 py-2 text-[11px] font-bold text-blue-900 shadow-sm border border-white/50 whitespace-nowrap overflow-hidden text-ellipsis">
                    Parsed 14 IAM roles successfully.
                  </div>
                  <div className="bg-white/50 backdrop-blur-md rounded-md px-3 py-2 text-[11px] font-bold text-blue-900 shadow-sm border border-white/50 whitespace-nowrap overflow-hidden text-ellipsis">
                    S3 Bucket 'logs-prod' analyzed.
                  </div>
               </div>

               {/* Large Copilot image overlapping bottom right, adjusted upward slightly to clear button */}
               <div className="absolute bottom-16 -right-2 flex items-end justify-end pointer-events-none z-10 overflow-visible mt-auto">
                 <img src="/copilot.png" className="w-[85%] max-w-[240px] object-contain drop-shadow-xl opacity-95" alt="Copilot Background" />
               </div>

               {/* Button below image, pinned to bottom */}
               <div className="mt-auto relative z-20 w-full pt-4">
                 <button onClick={onCopilotClick} className="w-full py-3 bg-white/70 hover:bg-white backdrop-blur-xl rounded-[14px] text-blue-800 text-[12px] font-bold transition-all border border-white shadow-sm flex justify-center items-center gap-1.5 focus:outline-none">
                   Enter War Room <ChevronRight size={14} />
                 </button>
               </div>
             </div>
          </motion.div>
        </div>

        {/* Bottom Area - Fast list (Sky Theme UI) */}
        <div className="bg-white/70 backdrop-blur-xl rounded-[20px] p-4 shadow-sm border border-white flex flex-col shrink-0 min-h-[180px]">
          <div className="mb-3 flex justify-between items-center shrink-0">
            <div>
              <h3 className="text-[13px] font-bold text-slate-800">Sovereign Remediations</h3>
            </div>
            <button className="text-[10px] font-bold text-blue-600 bg-blue-50 border border-blue-100 px-3 py-1.5 rounded-full hover:bg-blue-100 transition-colors">Historical Logs</button>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-x-8 gap-y-2 flex-1 overflow-auto scrollbar-hide content-start pr-1">
            <RiskItem icon={<Database size={14} className="text-blue-400" />} title="RDS Public Snapshots" resource="db-backup-prod" tagVal="SOVEREIGN FIXED" tagColor="bg-blue-50 text-blue-600 border border-blue-200 font-bold" />
            <RiskItem icon={<Shield size={14} className="text-blue-400" />} title="IAM Admin Privileges" resource="user/dev" tagVal="DISSIPATING" tagColor="bg-blue-50 text-blue-600 border border-blue-200 font-bold" />
            <RiskItem icon={<BookOpen size={14} className="text-blue-400" />} title="S3 Default Encryption" resource="assets-bucket" tagVal="SOVEREIGN FIXED" tagColor="bg-blue-50 text-blue-600 border border-blue-200 font-bold" />
          </div>
        </div>
      </main>

      <aside className="w-[320px] hidden 2xl:flex flex-col gap-3 h-full shrink-0 overflow-hidden pb-1 pt-1 border-l border-slate-200/50 pl-4 relative">
        {/* Sky Theme Reformatted Sovereign Log */}
        <div className="bg-white/80 backdrop-blur-2xl rounded-[20px] p-5 flex flex-col shadow-sm border border-white flex-1 min-h-0 relative">
           <h3 className="text-[15px] font-bold text-blue-700 mb-1 flex items-center gap-2">
             <Activity size={18} /> The Sovereign Log
           </h3>
           <p className="text-[10px] text-blue-400 mb-5 font-mono uppercase tracking-widest border-b border-blue-100 pb-3">Stream: active_nodes_us_1</p>
           
           <div className="flex flex-col gap-4 flex-1 overflow-y-auto scrollbar-hide pr-1">
              <LogTerminalItem time="14:02:45" action="[VETO]" target="Surgeon blocked over-privileged script (boto3:FullAccess)" rule="J-Delta: 0.82" />
              <LogTerminalItem time="13:58:12" action="[GOVERN]" target="NIST AI RMF 2.1 Robustness check: PASSED" rule="Compliance" />
              <LogTerminalItem time="13:30:00" action="[SHUTDOWN]" target="Shadow AI spawn neutralized autonomously" rule="TempLead: +3" />
              <LogTerminalItem time="12:15:22" action="[ROTATED]" target="IAM Access Keys replaced smoothly." rule="KeyAgePolicy" />
              <LogTerminalItem time="10:30:00" action="[NOTIFIED]" target="Dev team alerted about upcoming scaling." rule="Threshold: 80%" />
           </div>
        </div>
      </aside>
    </motion.div>
  );
}
