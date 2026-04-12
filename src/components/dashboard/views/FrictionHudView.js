import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { MessageSquare, ShieldAlert } from 'lucide-react';
import NegotiationLog from '../components/NegotiationLog';

export default function FrictionHudView() {
  const [countdown, setCountdown] = useState(10);

  useEffect(() => {
    const int = setInterval(() => {
      setCountdown(prev => (prev > 0 ? prev - 1 : 10));
    }, 1000);
    return () => clearInterval(int);
  }, []);

  return (
    <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -15 }} transition={{ duration: 0.3 }}  className="flex-1 h-full flex flex-col bg-transparent overflow-hidden px-1 py-1 absolute inset-0 w-full">
      <header className="flex justify-between items-center h-[40px] shrink-0 mb-3">
        <h1 className="text-[20px] font-bold tracking-tight text-slate-800 flex items-center gap-2">
          The Friction HUD 
        </h1>
        <div className="px-4 py-1.5 bg-rose-50 text-rose-600 font-bold text-[11px] rounded-lg border border-rose-200 flex items-center gap-2 shadow-sm">
          <div className="w-2 h-2 rounded-full bg-rose-500 animate-ping"></div> Live Monitoring
        </div>
      </header>
      
      <div className="flex-1 flex gap-4 pb-2">
        {/* Left Side: Negotiation Trace */}
        <div className="flex-[2] bg-white/70 backdrop-blur-2xl rounded-[20px] shadow-sm border border-white p-6 flex flex-col relative overflow-hidden">
           <h2 className="text-[15px] font-bold text-slate-800 flex items-center gap-2 mb-6 pb-4 border-b border-slate-200">
             <MessageSquare size={16} className="text-blue-500" /> The Negotiation Trace
           </h2>
           
           <div className="flex-1 overflow-y-auto pr-2 scrollbar-hide flex flex-col gap-6">
              <NegotiationLog 
                timestamp="14:22:04.110"
                controller="Proposed full shutdown of 'cluster-ai-dev' to save $120.00."
                ciso="Vetoed. Remediation cost of downtime ($5,000) exceeds risk delta."
                status="VETO STANDS"
                statusColor="bg-amber-50 text-amber-700 border-amber-300 shadow-sm"
              />
               <NegotiationLog 
                timestamp="14:20:11.050"
                controller="Proposed downgrade of EC2 instance i-0abcd to t3.medium."
                ciso="Approved. Negligible compliance impact. Expected savings: $40/mo."
                status="SOVEREIGN FIX EXECUTED"
                statusColor="bg-emerald-50 text-emerald-700 border-emerald-300 shadow-sm"
              />
               <NegotiationLog 
                timestamp="14:15:30.900"
                controller="Identified unencrypted S3 bucket: 'logs-archive'."
                ciso="Overriding read-only mode to inject AWS KMS AES-256."
                status="ENFORCED BY POLICY"
                statusColor="bg-blue-50 text-blue-700 border-blue-300 shadow-sm"
              />
           </div>
        </div>

        {/* Right Side: Fast-Pass Countdown (Light theme approach, very striking) */}
        <div className="flex-[1] bg-gradient-to-b from-white/90 to-rose-50/50 rounded-[20px] shadow-sm border border-rose-100 p-6 flex flex-col items-center justify-center text-center relative overflow-hidden">
          <div className="absolute inset-0 opacity-[0.2]" style={{ backgroundImage: "repeating-linear-gradient(45deg, transparent, transparent 10px, #fecdd3 10px, #fecdd3 20px)" }}></div>
          
          <div className="relative z-10 w-full">
            <h3 className="text-rose-600 font-bold text-[12px] uppercase tracking-widest mb-6 drop-shadow-sm">Predictive Fast-Pass Trigger</h3>
            
            <div className="bg-white border-[4px] border-rose-200 rounded-full w-44 h-44 mx-auto flex items-center justify-center shadow-[0_10px_30px_rgba(244,63,94,0.15)] relative flex-col">
               <span className="text-[64px] font-bold text-slate-800 leading-none font-mono tracking-tighter">
                 {countdown.toString().padStart(2, '0')}
               </span>
               <span className="text-[10px] text-rose-500 font-bold mt-2 uppercase tracking-wider">SEC TO AUTO-KILL</span>
            </div>

            <div className="mt-8 bg-white/90 backdrop-blur-sm p-5 rounded-[16px] border border-rose-200 shadow-sm">
              <div className="text-[14px] font-bold text-slate-800 mb-1 flex justify-center items-center gap-1.5"><ShieldAlert size={14} className="text-rose-500"/> Shadow AI Spawn Detected</div>
              <div className="text-[11px] text-slate-500 font-mono font-medium">Location: us-east-2/eks-cluster</div>
              <div className="text-[13px] text-emerald-600 font-bold mt-3 border-t border-slate-100 pt-3">
                Guaranteed Savings: $1,450/mo
              </div>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
