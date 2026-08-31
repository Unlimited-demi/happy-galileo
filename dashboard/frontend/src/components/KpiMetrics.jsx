import React from 'react';
import { Server, Cpu, Globe, AlertTriangle } from 'lucide-react';
import { Card } from '@/components/ui/card';

export function KpiMetrics({ totalNodes, totalContainers, totalServices, openIncidentsCount }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      <Card className="p-5 flex items-center justify-between border-border/60 bg-card/60 backdrop-blur-sm hover:border-border transition-all duration-300">
        <div>
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-1">
            Total Nodes
          </div>
          <div className="text-2xl font-bold text-slate-100 tracking-tight">{totalNodes}</div>
        </div>
        <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shadow-inner">
          <Server className="w-5 h-5" />
        </div>
      </Card>

      <Card className="p-5 flex items-center justify-between border-border/60 bg-card/60 backdrop-blur-sm hover:border-border transition-all duration-300">
        <div>
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-1">
            Monitored Containers
          </div>
          <div className="text-2xl font-bold text-slate-100 tracking-tight">{totalContainers}</div>
        </div>
        <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 shadow-inner">
          <Cpu className="w-5 h-5" />
        </div>
      </Card>

      <Card className="p-5 flex items-center justify-between border-border/60 bg-card/60 backdrop-blur-sm hover:border-border transition-all duration-300">
        <div>
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-1">
            Active Services
          </div>
          <div className="text-2xl font-bold text-slate-100 tracking-tight">{totalServices}</div>
        </div>
        <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 shadow-inner">
          <Globe className="w-5 h-5" />
        </div>
      </Card>

      <Card
        className={`p-5 flex items-center justify-between transition-all duration-300 border-border/60 backdrop-blur-sm ${
          openIncidentsCount > 0
            ? 'border-rose-500/40 bg-rose-500/10'
            : 'bg-card/60 hover:border-border'
        }`}
      >
        <div>
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-1">
            Open Incidents
          </div>
          <div
            className={`text-2xl font-bold tracking-tight ${
              openIncidentsCount > 0 ? 'text-rose-400' : 'text-slate-100'
            }`}
          >
            {openIncidentsCount}
          </div>
        </div>
        <div
          className={`w-10 h-10 rounded-xl flex items-center justify-center shadow-inner ${
            openIncidentsCount > 0
              ? 'bg-rose-500/20 border border-rose-500/30 text-rose-400'
              : 'bg-muted/50 border border-border/60 text-muted-foreground'
          }`}
        >
          <AlertTriangle className="w-5 h-5" />
        </div>
      </Card>
    </div>
  );
}
