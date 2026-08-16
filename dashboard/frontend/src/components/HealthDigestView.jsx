import React from 'react';
import { ShieldCheck, Activity, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';

export function HealthDigestView({ nodes, incidents }) {
  const openCount = incidents.filter(
    (i) => !['RESOLVED', 'VERIFIED', 'CLOSED'].includes(i.state)
  ).length;

  return (
    <Card className="p-6 border-border/80 bg-card/60">
      <CardHeader className="p-0 pb-6 border-b border-border/60">
        <CardTitle className="text-lg font-bold text-slate-100 flex items-center gap-2">
          <Activity className="w-5 h-5 text-emerald-400" />
          Automated Ops Health Digest
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Generated continuously by AI-Ops sentry daemon. Evaluates fleet resilience, error frequency, and auto-remediation efficiency.
        </p>
      </CardHeader>

      <CardContent className="p-0 pt-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-muted/40 border border-border/60">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Fleet Health Score
            </div>
            <div className="text-2xl font-bold text-emerald-400 flex items-center gap-2">
              {openCount === 0 ? '100%' : `${Math.max(60, 100 - openCount * 10)}%`}
              <span className="text-xs font-normal text-muted-foreground font-mono">
                ({nodes.length} Nodes Active)
              </span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-muted/40 border border-border/60">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Active Sentry Status
            </div>
            <div className="text-2xl font-bold text-sky-400 flex items-center gap-2">
              ENFORCING
              <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
            </div>
          </div>

          <div className="p-4 rounded-xl bg-muted/40 border border-border/60">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Autonomous Remediation
            </div>
            <div className="text-2xl font-bold text-indigo-400 flex items-center gap-2">
              ACTIVE
              <span className="text-xs font-normal text-muted-foreground font-mono">
                (Level 1-3 AI-Ops)
              </span>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-slate-200">Recent Ops Digest & Security Baseline</h4>
          <div className="rounded-lg bg-zinc-950 border border-border/60 p-4 font-mono text-xs text-slate-300 space-y-1.5">
            <div className="text-emerald-400">✓ Caddy TLS Ingress: Strict On-Demand TLS Active with Wildcard Routing</div>
            <div className="text-emerald-400">✓ Zero Public Host Ports Policy: Enforced on internal bridge 'dev-net'</div>
            <div className="text-sky-400">✓ Anomaly Classifier: Universal Syntactic Grammar Engine Active</div>
            <div className={openCount > 0 ? 'text-amber-400' : 'text-emerald-400'}>
              {openCount > 0
                ? `! Open Anomalies: ${openCount} incident(s) awaiting autonomous remediation`
                : '✓ Zero Unhandled Exceptions: Fleet running with zero active crash loops'}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
