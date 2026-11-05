import React, { useState } from 'react';
import { AlertTriangle, FileText, Terminal as TerminalIcon, X, Copy, ShieldCheck } from 'lucide-react';
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

  const isVerified = ['VERIFIED', 'MERGED'].includes(incident.state);
  const isUnverified = incident.state === 'RESOLVED_UNVERIFIED';
  const isResolved = isVerified || isUnverified || ['RESOLVED', 'CLOSED'].includes(incident.state);
  const isClaimed = incident.state === 'CLAIMED';
  const evidence = incident.evidence || {};
  const proof = incident.resolution_proof || {};
  const stack = evidence.stack_trace || evidence.logs || 'No stack trace captured.';

  const hasProof = !!incident.resolution_proof || !!incident.resolved_at;
  const [activeTab, setActiveTab] = useState(hasProof ? 'proof' : isClaimed ? 'terminal' : 'dossier');

  return (
    <Dialog open={!!incident} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl p-6 bg-card border-border/80 text-foreground">
        <DialogHeader className="flex flex-row items-center justify-between pb-4 border-b border-border/60">
          <div className="flex items-center gap-2.5">
            <AlertTriangle
              className={`w-5 h-5 ${isVerified ? 'text-emerald-400' : isUnverified ? 'text-amber-400' : 'text-rose-400'}`}
            />
            <DialogTitle className="text-base font-bold text-slate-100 flex items-center gap-2">
              Incident: <span className="font-mono text-sky-400">{incident.id}</span>
              <Badge variant={isVerified ? 'success' : isUnverified ? 'warning' : isClaimed ? 'warning' : 'destructive'} className="text-[10px]">
                {isVerified ? (incident.state === 'MERGED' ? 'MERGED' : 'VERIFIED') : isUnverified ? 'RESOLVED (UNVERIFIED)' : incident.state}
              </Badge>
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

        {/* Radix Tabs for Dossier vs In-Browser Terminal vs Resolution Proof */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full mt-2">
          <TabsList className={`grid w-full ${hasProof ? 'grid-cols-3' : 'grid-cols-2'}`}>
            <TabsTrigger value="dossier" className="gap-2 text-xs">
              <FileText className="w-4 h-4" />
              Diagnostic Dossier
            </TabsTrigger>
            {hasProof && (
              <TabsTrigger value="proof" className="gap-2 text-xs">
                <ShieldCheck className="w-4 h-4" />
                Resolution Proof
              </TabsTrigger>
            )}
            <TabsTrigger value="terminal" className="gap-2 text-xs">
              <TerminalIcon className="w-4 h-4" />
              ⚡ Stream Terminal
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

          {/* Tab: Resolution Proof */}
          {hasProof && (
            <TabsContent value="proof" className="space-y-4 pt-2">
              <div className="p-4 rounded-lg bg-zinc-950 border border-border/60 space-y-3 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-border/40 pb-2">
                  <span className="text-muted-foreground uppercase text-[10px]">Verification Status</span>
                  <Badge variant={isVerified ? 'success' : isUnverified ? 'warning' : 'destructive'} className="text-xs">
                    {isVerified ? 'VERIFIED & RESOLVED' : isUnverified ? 'RESOLVED (UNVERIFIED)' : incident.state}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-2 text-slate-300">
                  <div><span className="text-muted-foreground">Resolved By:</span> {incident.claimed_by || 'N/A'}</div>
                  <div><span className="text-muted-foreground">Resolved At:</span> {incident.resolved_at || 'N/A'}</div>
                  <div><span className="text-muted-foreground">Container State:</span> {proof.container_state || 'N/A'}</div>
                  <div><span className="text-muted-foreground">Health Probe:</span> {proof.health_probe || 'N/A'}</div>
                  <div><span className="text-muted-foreground">Git Branch:</span> {proof.git_branch || 'N/A'}</div>
                  <div><span className="text-muted-foreground">Git Commit:</span> {proof.git_commit || 'N/A'}</div>
                  <div className="col-span-2"><span className="text-muted-foreground">Git Push:</span> {proof.git_push_status || 'N/A'}</div>
                  {proof.live_url && (
                    <div className="col-span-2">
                      <span className="text-muted-foreground">Live URL:</span>{' '}
                      <a href={proof.live_url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                        {proof.live_url}
                      </a>
                    </div>
                  )}
                </div>
              </div>

              {incident.resolution_notes && (
                <div>
                  <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                    Remediation & Root Cause Summary
                  </div>
                  <div className="rounded-lg bg-secondary/50 border border-border/60 p-4 text-xs text-slate-200 leading-relaxed whitespace-pre-wrap">
                    {incident.resolution_notes}
                  </div>
                </div>
              )}

              {proof.git_diff && proof.git_diff !== 'No git diff recorded.' && (
                <div>
                  <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                    Code Diff / Files Modified
                  </div>
                  <div className="rounded-lg bg-zinc-950 border border-border/80 p-4 font-mono text-xs text-slate-300 max-h-48 overflow-y-auto whitespace-pre-wrap">
                    {proof.git_diff}
                  </div>
                </div>
              )}
            </TabsContent>
          )}

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
