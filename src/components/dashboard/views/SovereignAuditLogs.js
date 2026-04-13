import React from 'react';
import { motion } from 'framer-motion';
import { Download, ShieldAlert } from 'lucide-react';
import AuditRow from '../components/AuditRow';

export default function SovereignAuditLogs() {
  return (
    <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -15 }} transition={{ duration: 0.3 }}  className="flex-1 h-full flex flex-col bg-transparent overflow-hidden px-1 py-1 absolute inset-0 w-full">
      <header className="flex justify-between items-center h-[40px] shrink-0 mb-3">
        <h1 className="text-[20px] font-bold tracking-tight text-slate-800 flex items-center gap-2">
           The NIST Sovereign Audit
        </h1>
        <button className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-[12px] text-[12px] font-bold transition-all shadow-md">
          <Download size={14} /> Download Sovereign Safety Report
        </button>
      </header>
      
      {/* Light Clean Data List */}
      <div className="flex-1 bg-white/90 rounded-[20px] shadow-sm overflow-hidden flex flex-col p-6 mb-2 border border-slate-200 relative backdrop-blur-xl">
        
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-100 shrink-0">
          <div className="flex items-center gap-3 bg-slate-50 border border-slate-100 px-4 py-2 rounded-xl text-slate-800 font-bold text-[12px] uppercase tracking-widest font-mono">
             <ShieldAlert className="text-blue-600" size={16} />
             Forensic Black-Box Recorder [Active]
          </div>
          <div className="flex gap-2 opacity-50">
            <div className="w-3 h-3 rounded-full bg-slate-300"></div><div className="w-3 h-3 rounded-full bg-slate-300"></div><div className="w-3 h-3 rounded-full bg-slate-300"></div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto w-full flex flex-col text-[12.5px] font-sans font-medium text-slate-700">
           
           <AuditRow time="14:02:45.302" action="[VETO]" color="text-rose-600 bg-rose-50 border-rose-200" desc="Surgeon blocked over-privileged IAM script (boto3:FullAccess detected). Terminating user active session dynamically." />
           <AuditRow time="14:03:10.000" action="[KERNEL]" color="text-indigo-600 bg-indigo-50 border-indigo-200" desc="J-Score matrix calculation initiated for resource: prod_rds_cluster_main." />
           <AuditRow time="14:03:12.441" action="[GOVERN]" color="text-emerald-600 bg-emerald-50 border-emerald-200" desc="NIST AI RMF 2.1 Robustness check: PASSED. Configuration validated." />
           <AuditRow time="14:04:00.111" action="[SHUTDOWN]" color="text-amber-600 bg-amber-50 border-amber-200" desc={<span>Shadow AI spawn neutralized autonomously. Estimated monthly savings: <strong className="text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-100 ml-1">$140/hr</strong></span>} />
           <AuditRow time="14:05:00.100" action="[ROTATED]" color="text-blue-600 bg-blue-50 border-blue-200" desc="IAM Access Keys replaced smoothly." />

           <div className="mt-8 flex items-center gap-2 pl-4 text-slate-400 font-mono font-bold max-w-max border border-slate-100 bg-slate-50 px-4 py-2 rounded-lg">
             sovereign@core:~$
             <div className="w-2.5 h-4 bg-blue-500 animate-pulse rounded-sm relative top-[1px]"></div>
           </div>
        </div>
      </div>
    </motion.div>
  );
}
