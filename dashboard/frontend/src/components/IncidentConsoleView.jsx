import React from 'react';
import { ShieldAlert, FileText, Terminal as TerminalIcon, ShieldCheck } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';

export function IncidentConsoleView({ incidents, onSelect, onDispatch, onPurge }) {
  if (!incidents || incidents.length === 0) {
    return (
      <Card className="p-12 text-center border-dashed border-border/80 bg-card/40">
        <div className="flex flex-col items-center justify-center">
          <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-3">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-slate-200">All systems operating nominally</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm">
            Zero active incidents or unresolved exceptions recorded across the fleet.
          </p>
        </div>
      </Card>
    );
  }

  const openCount = incidents.filter(
    (i) => !['RESOLVED', 'VERIFIED', 'CLOSED'].includes(i.state)
  ).length;

  return (
    <div className="space-y-4">
      {/* Top Console Action Bar */}
      <div className="flex items-center justify-between pb-2">
        <div className="text-xs text-muted-foreground font-medium">
          Showing {incidents.length} incident(s) • <span className="text-rose-400 font-semibold">{openCount} actionable open</span>
        </div>
        <Button variant="secondary" size="sm" onClick={onPurge} className="gap-1.5 h-8 text-xs">
          <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
          Purge / Clear Dossiers
        </Button>
      </div>

      {/* Incident Cards Grid */}
      <div className="space-y-4">
        {incidents.map((inc) => {
          const isResolved = ['RESOLVED', 'VERIFIED', 'CLOSED'].includes(inc.state);
          const isClaimed = inc.state === 'CLAIMED';
          const stack = inc.evidence?.stack_trace || inc.evidence?.logs || 'No stack trace captured.';
          const pct = isResolved ? 100 : isClaimed ? 60 : 20;

          return (
            <Card
              key={inc.id}
              className={`border-l-4 transition-all ${
                isResolved
                  ? 'border-l-emerald-500 border-border/60 bg-card/40 opacity-85'
                  : isClaimed
                  ? 'border-l-amber-500 border-border bg-card/80'
                  : 'border-l-rose-500 border-border bg-card'
              }`}
            >
              <CardContent className="p-5 space-y-3.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 font-mono text-xs">
                    <Badge variant="outline" className="font-mono bg-zinc-900 border-border text-slate-200">
                      {inc.id}
                    </Badge>
                    <Badge variant={isResolved ? 'success' : isClaimed ? 'warning' : 'destructive'}>
                      {isClaimed ? `CLAIMED (${inc.claimed_by || 'OpenCode'})` : inc.state || 'DETECTED'}
                    </Badge>
                    <span className="text-muted-foreground font-sans text-xs">
                      • {inc.source_node || 'Primary Node'}
                    </span>
                  </div>
                  <span className="text-[11px] text-muted-foreground font-mono">
                    {inc.created_at || ''}
                  </span>
                </div>

                <div>
                  <h4 className="text-sm font-bold text-slate-100">
                    {inc.service_name && <span className="text-sky-400">[{inc.service_name}] </span>}
                    {inc.title}
                  </h4>
                </div>

                {!isResolved && (
                  <div className="rounded-lg bg-zinc-950/80 border border-border/50 p-3 font-mono text-xs text-rose-300 max-h-24 overflow-y-auto whitespace-pre-wrap">
                    {stack}
                  </div>
                )}

                {/* Progress bar */}
                <div className="space-y-1.5 pt-1">
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{isClaimed ? 'Remediation: In Progress (OpenCode)' : 'Remediation Pipeline'}</span>
                    <span className="font-mono">{pct}%</span>
                  </div>
                  <Progress
                    value={pct}
                    className={`h-1.5 ${
                      isResolved
                        ? '[&>div]:bg-emerald-400'
                        : isClaimed
                        ? '[&>div]:bg-amber-400'
                        : '[&>div]:bg-rose-400'
                    }`}
                  />
                </div>

                {/* Action Buttons */}
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onSelect(inc)}
                    className="flex-1 text-xs gap-1.5 h-8"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    Diagnostic Dossier
                  </Button>
                  {!isResolved && (
                    <Button
                      variant={isClaimed ? 'amber' : 'default'}
                      size="sm"
                      onClick={() => onDispatch && onDispatch(inc.id)}
                      className="text-xs gap-1.5 h-8 font-semibold"
                    >
                      <TerminalIcon className="w-3.5 h-3.5" />
                      {isClaimed ? 'Re-Dispatch' : '⚡ Dispatch OpenCode'}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
