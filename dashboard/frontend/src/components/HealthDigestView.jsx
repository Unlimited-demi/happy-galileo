import React from 'react';
import { ShieldCheck, Activity, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';

export function HealthDigestView({ nodes, incidents }) {
  const openCount = incidents.filter(
    (i) => !['RESOLVED', 'VERIFIED', 'RESOLVED_UNVERIFIED', 'MERGED', 'CLOSED'].includes(i.state)
  ).length;

  const verifiedCount = incidents.filter(
    (i) => ['VERIFIED', 'MERGED'].includes(i.state)
  ).length;

  const totalContainers = nodes.reduce((acc, n) => acc + (n.containers_count || 0), 0);
  const totalServices = nodes.reduce((acc, n) => acc + (n.services?.length || 0), 0);
  const baseDomain = nodes[0]?.base_domain || 'dev-server.datakrib.com';

  return (
    <Card className="p-6 border-border/80 bg-card/60">
      <CardHeader className="p-0 pb-6 border-b border-border/60">
        <CardTitle className="text-lg font-bold text-slate-100 flex items-center gap-2">
          <Activity className="w-5 h-5 text-emerald-400" />
          Automated Ops Health Digest
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Real-time fleet health aggregation. Reflects actual live Docker runtime states, registered service routes, and verified incident resolutions.
        </p>
      </CardHeader>

      <CardContent className="p-0 pt-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-muted/40 border border-border/60">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Fleet Status
            </div>
            <div className={`text-2xl font-bold flex items-center gap-2 ${openCount === 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
              {openCount === 0 ? 'NOMINAL' : `${openCount} ISSUES`}
              <span className="text-xs font-normal text-muted-foreground font-mono">
                ({nodes.length} {nodes.length === 1 ? 'Node' : 'Nodes'})
              </span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-muted/40 border border-border/60">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Active Monitored Fleet
            </div>
            <div className="text-2xl font-bold text-sky-400 flex items-center gap-2">
              {totalContainers}
              <span className="text-xs font-normal text-muted-foreground font-mono">
                Containers across {totalServices} Services
              </span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-muted/40 border border-border/60">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Verified Auto-Remediations
            </div>
            <div className="text-2xl font-bold text-indigo-400 flex items-center gap-2">
              {verifiedCount}
              <span className="text-xs font-normal text-muted-foreground font-mono">
                of {incidents.length} Incident Dossiers
              </span>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-slate-200">Live Operating Baseline & Telemetry</h4>
          <div className="rounded-lg bg-zinc-950 border border-border/60 p-4 font-mono text-xs text-slate-300 space-y-1.5">
            <div className="text-emerald-400">● Wildcard Ingress Scope: `*.{baseDomain}`</div>
            <div className="text-sky-400">● Docker Bridge Network: Internal communication on `dev-net`</div>
            <div className="text-slate-300">● Incident Records: {incidents.length} total recorded ({verifiedCount} verified, {openCount} active)</div>
            <div className={openCount > 0 ? 'text-amber-400' : 'text-emerald-400'}>
              {openCount > 0
                ? `! Active Issues: ${openCount} incident(s) requiring remediation or verification`
                : '✓ Zero Open Incidents: All monitored services operating without active error dossiers'}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
