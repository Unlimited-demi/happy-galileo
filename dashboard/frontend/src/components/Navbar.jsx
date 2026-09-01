import React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function Navbar({ baseDomain, onRefresh }) {
  return (
    <header className="flex items-center justify-between py-4 border-b border-border/60 mb-8">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">ARA</h1>
          <span className="text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded-full">
            Autonomous Remediation Agent
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          Fleet Management & Autonomous AI-Ops | *.{baseDomain || 'dev-server.datakrib.com'}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-medium text-emerald-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          Live Telemetry
        </div>
        <Button variant="secondary" size="sm" onClick={onRefresh} className="gap-1.5 h-8">
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </Button>
      </div>
    </header>
  );
}
