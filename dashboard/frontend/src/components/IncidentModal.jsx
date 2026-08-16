import React, { useState } from 'react';
import { AlertTriangle, FileText, Terminal as TerminalIcon, X, Copy } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Terminal } from '@/components/Terminal';

export function IncidentModal({ incident, onClose, onCopy, onDispatch }) {
  if (!incident) return null;

  const isResolved = ['RESOLVED', 'VERIFIED', 'CLOSED'].includes(incident.state);
  const isClaimed = incident.state === 'CLAIMED';
  const evidence = incident.evidence || {};
  const stack = evidence.stack_trace || evidence.logs || 'No stack trace captured.';

  const [activeTab, setActiveTab] = useState(isClaimed ? 'terminal' : 'dossier');

  return (
    <Dialog open={!!incident} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl p-6 bg-card border-border/80 text-foreground">
        <DialogHeader className="flex flex-row items-center justify-between pb-4 border-b border-border/60">
          <div className="flex items-center gap-2.5">
            <AlertTriangle
              className={`w-5 h-5 ${isResolved ? 'text-emerald-400' : 'text-rose-400'}`}
            />
            <DialogTitle className="text-base font-bold text-slate-100">
              Incident: <span className="font-mono text-sky-400">{incident.id}</span>
            </DialogTitle>
          </div>

          <div className="flex items-center gap-2 pr-6">
            {!isResolved && (
              <Button
                variant={isClaimed ? 'amber' : 'default'}
                size="sm"
                onClick={() => onDispatch && onDispatch(incident.id)}
                className="h-7 text-xs gap-1.5 font-semibold"
              >
                <TerminalIcon className="w-3.5 h-3.5" />
                {isClaimed ? 'Re-Dispatch' : '⚡ Dispatch OpenCode'}
              </Button>
            )}
          </div>
        </DialogHeader>

        {/* Radix Tabs for Dossier vs In-Browser Terminal */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full mt-2">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="dossier" className="gap-2 text-xs">
              <FileText className="w-4 h-4" />
              Diagnostic Dossier
            </TabsTrigger>
            <TabsTrigger value="terminal" className="gap-2 text-xs">
              <TerminalIcon className="w-4 h-4" />
              ⚡ Live In-Browser Tmux Terminal
              {isClaimed && <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />}
            </TabsTrigger>
          </TabsList>

          {/* Tab 1: Diagnostic Dossier Content */}
          <TabsContent value="dossier" className="space-y-4 pt-2">
            <div>
              <h4 className="text-sm font-bold text-slate-100 mb-1">{incident.title}</h4>
              <p className="text-xs text-muted-foreground font-mono">
                Service: {incident.service_name} • Node: {incident.source_node || 'Primary'} • Detected: {incident.created_at}
              </p>
            </div>

            <div>
              <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                Error Stack Trace / Runtime Evidence
              </div>
              <div className="rounded-lg bg-zinc-950 border border-border/80 p-4 font-mono text-xs text-rose-300 max-h-60 overflow-y-auto whitespace-pre-wrap">
                {stack}
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                AI-Ops Diagnostic Recommendation
              </div>
              <div className="rounded-lg bg-secondary/50 border border-border/60 p-4 text-xs text-slate-200 leading-relaxed">
                {incident.recommendation || 'Investigate container runtime logs and apply targeted patch.'}
              </div>
            </div>
          </TabsContent>

          {/* Tab 2: Interactive XTerm Terminal */}
          <TabsContent value="terminal" className="pt-2">
            <Terminal
              sessionName={`opencode-${incident.id}`}
              onCopy={onCopy}
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
