import React from 'react';
import { Server, Cpu, Globe, AlertTriangle } from 'lucide-react';
import { Card } from '@/components/ui/card';

export function KpiMetrics({ totalNodes, totalContainers, totalServices, openIncidentsCount }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      <Card className="p-5 flex items-center justify-between hover:border-border transition-colors">
        <div>
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
            Total Nodes
          </div>
          <div className="text-2xl font-bold text-slate-100">{totalNodes}</div>
        </div>
        <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
          <Server className="w-5 h-5" />
        </div>
      </Card>

      <Card className="p-5 flex items-center justify-between hover:border-border transition-colors">
        <div>
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
            Monitored Containers
          </div>
          <div className="text-2xl font-bold text-slate-100">{totalContainers}</div>
        </div>
        <div className="w-10 h-10 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
          <Cpu className="w-5 h-5" />
        </div>
      </Card>

      <Card className="p-5 flex items-center justify-between hover:border-border transition-colors">
        <div>
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
            Active Services
          </div>
          <div className="text-2xl font-bold text-slate-100">{totalServices}</div>
        </div>
        <div className="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
          <Globe className="w-5 h-5" />
        </div>
      </Card>

      <Card
        className={`p-5 flex items-center justify-between transition-colors ${
          openIncidentsCount > 0
            ? 'border-rose-500/40 bg-rose-500/5'
            : 'hover:border-border'
        }`}
      >
        <div>
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
            Open Incidents
          </div>
          <div
            className={`text-2xl font-bold ${
              openIncidentsCount > 0 ? 'text-rose-400' : 'text-slate-100'
            }`}
          >
            {openIncidentsCount}
          </div>
        </div>
        <div
          className={`w-10 h-10 rounded-lg flex items-center justify-center ${
            openIncidentsCount > 0
              ? 'bg-rose-500/15 border border-rose-500/30 text-rose-400'
              : 'bg-muted border border-border text-muted-foreground'
          }`}
        >
          <AlertTriangle className="w-5 h-5" />
        </div>
      </Card>
    </div>
  );
}
