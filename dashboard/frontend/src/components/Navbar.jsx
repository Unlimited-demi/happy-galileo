import React from 'react';
import { RefreshCw, KeyRound, Shield } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function Navbar({ baseDomain, onRefresh, currentRole, onOpenAuth }) {
  const getRoleBadge = (role) => {
    const r = (role || 'viewer').toLowerCase();
    if (r === 'admin') {
      return { label: 'Admin', class: 'bg-purple-500/10 text-purple-400 border-purple-500/30' };
    }
    if (r === 'operator') {
      return { label: 'Operator', class: 'bg-blue-500/10 text-blue-400 border-blue-500/30' };
    }
    if (r === 'approver') {
      return { label: 'Approver', class: 'bg-amber-500/10 text-amber-400 border-amber-500/30' };
    }
    return { label: 'Viewer', class: 'bg-slate-500/10 text-slate-400 border-slate-500/30' };
  };

  const badge = getRoleBadge(currentRole);

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
          Fleet Management & Autonomous AI-Ops | *.{baseDomain || 'suburbancloud.ng'}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-medium text-emerald-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          Live Telemetry
        </div>

        <button
          onClick={onOpenAuth}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-all hover:opacity-80 ${badge.class}`}
          title="Click to view or change ARA API Key / RBAC Role"
        >
          <KeyRound className="w-3 h-3" />
          <span>{badge.label}</span>
        </button>

        <Button variant="secondary" size="sm" onClick={onRefresh} className="gap-1.5 h-8">
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </Button>
      </div>
    </header>
  );
}
