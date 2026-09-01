import React from 'react';
import { Cpu, Globe, AlertTriangle, ExternalLink, Copy, Lock, HardDrive, MemoryStick } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export function FleetMatrixView({ nodes, onCopy }) {
  return (
    <div className="space-y-6">
      {nodes.map((node, idx) => {
        const isOnline = node.online !== false;
        const services = node.services || [];
        return (
          <Card key={node.node_name || idx} className="overflow-hidden border-border/80 bg-card/60 backdrop-blur-sm">
            <CardHeader className="bg-muted/30 border-b border-border/60 py-4 px-6 flex flex-row items-center justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`w-3 h-3 rounded-full ${
                    isOnline ? 'bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.5)]' : 'bg-zinc-500'
                  }`}
                />
                <div>
                  <CardTitle className="text-base font-bold text-slate-100 flex items-center gap-2">
                    {node.node_name || 'Primary Controller'}
                    <span className="text-xs font-mono font-normal text-muted-foreground">
                      ({node.client_ip || '127.0.0.1'})
                    </span>
                  </CardTitle>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Scope: *.{node.base_domain || 'dev-server.datakrib.com'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Badge variant={isOnline ? 'success' : 'secondary'}>
                  {isOnline ? 'ONLINE' : 'OFFLINE'}
                </Badge>
                <Badge variant="secondary" className="gap-1 font-mono">
                  <Cpu className="w-3 h-3 text-sky-400" />
                  {node.containers_count || 0} Containers
                </Badge>
                <Badge variant="secondary" className="gap-1 font-mono">
                  <Globe className="w-3 h-3 text-indigo-400" />
                  {services.length} Services
                </Badge>
                {node.open_incidents_count > 0 && (
                  <Badge variant="destructive" className="gap-1 font-mono">
                    <AlertTriangle className="w-3 h-3" />
                    {node.open_incidents_count} Issues
                  </Badge>
                )}
              </div>
            </CardHeader>

            {/* Node Metrics Bar */}
            {(() => {
              const sm = node.metrics?.server || {};
              const la = sm.load_average || {};
              const cores = sm.cpu_cores || 0;
              const mem = sm.memory || {};
              const memPct = mem.usage_percent || (mem.total_bytes ? ((mem.used_bytes / mem.total_bytes) * 100) : 0);
              const memUsedGB = ((mem.used_bytes || 0) / 1073741824).toFixed(1);
              const memTotalGB = ((mem.total_bytes || 0) / 1073741824).toFixed(1);
              const loadPct = cores > 0 ? ((la['5min'] || 0) / cores) * 100 : 0;
              const loadColor = loadPct > 90 ? 'text-rose-400' : loadPct > 70 ? 'text-amber-400' : 'text-slate-200';
              const hasMetrics = la['5min'] !== undefined || mem.total_bytes > 0;
              if (!hasMetrics) return null;
              return (
                <div className="flex items-center gap-6 px-6 py-2.5 bg-muted/15 border-b border-border/40 text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-3.5 h-3.5 text-sky-400" />
                    <span className="text-muted-foreground">CPU</span>
                    <span className={`font-semibold ${loadColor}`}>{loadPct.toFixed(0)}%</span>
                    <span className="text-muted-foreground text-[10px]">
                      ({(la['1min'] || 0).toFixed(2)} / {(la['5min'] || 0).toFixed(2)} / {(la['15min'] || 0).toFixed(2)} load
                      {cores > 0 ? ` on ${cores} cores` : ''})
                    </span>
                    {cores > 0 && (
                      <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden ml-1">
                        <div
                          className={`h-full rounded-full transition-all ${loadPct > 90 ? 'bg-rose-500' : loadPct > 70 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                          style={{ width: `${Math.min(loadPct, 100)}%` }}
                        />
                      </div>
                    )}
                  </div>
                  {mem.total_bytes > 0 && (
                    <div className="flex items-center gap-2">
                      <HardDrive className="w-3.5 h-3.5 text-amber-400" />
                      <span className="text-muted-foreground">Memory</span>
                      <span className={`font-semibold ${memPct > 80 ? 'text-rose-400' : memPct > 60 ? 'text-amber-400' : 'text-slate-200'}`}>
                        {memPct.toFixed(0)}%
                      </span>
                      <span className="text-muted-foreground text-[10px]">({memUsedGB}G / {memTotalGB}G)</span>
                      <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden ml-1">
                        <div
                          className={`h-full rounded-full transition-all ${memPct > 80 ? 'bg-rose-500' : memPct > 60 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                          style={{ width: `${Math.min(memPct, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted/20 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50">
                    <tr>
                      <th className="py-3 px-6">Service Name</th>
                      <th className="py-3 px-6">Type</th>
                      <th className="py-3 px-6">Port</th>
                      <th className="py-3 px-6">Container State</th>
                      <th className="py-3 px-6">Codebase / Git</th>
                      <th className="py-3 px-6 text-right">Access Endpoint</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40 font-mono text-xs">
                    {services.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="py-8 text-center text-muted-foreground font-sans">
                          No active services discovered on this node.
                        </td>
                      </tr>
                    ) : (
                      services.map((svc) => {
                        const isWeb = svc.container_type === 'web' || !!svc.url;
                        const statusText = svc.container_status || svc.status || 'UNKNOWN';
                        const isRunning = statusText.toLowerCase().startsWith('up');
                        const codebase = svc.codebase || {};
                        return (
                          <tr key={svc.service_name || svc.name} className="hover:bg-muted/30 transition-colors">
                            <td className="py-3 px-6 font-semibold text-slate-200">{svc.service_name || svc.container_name || svc.name}</td>
                            <td className="py-3 px-6 font-sans">
                              <Badge variant="outline" className="text-[11px] uppercase font-mono">
                                {svc.container_type || 'service'}
                              </Badge>
                            </td>
                            <td className="py-3 px-6 text-muted-foreground">{svc.port || '—'}</td>
                            <td className="py-3 px-6 font-sans">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={`w-2 h-2 rounded-full ${
                                    isRunning ? 'bg-emerald-400' : 'bg-rose-400'
                                  }`}
                                />
                                <span className={isRunning ? 'text-emerald-400 font-medium' : 'text-rose-400 font-medium'}>
                                  {statusText}
                                </span>
                              </div>
                            </td>
                            <td className="py-3 px-6 text-muted-foreground truncate max-w-xs">
                              <div className="flex flex-col gap-0.5">
                                <span className="text-slate-300 truncate" title={codebase.workspace_dir}>
                                  {codebase.workspace_dir || svc.workspace_dir || '[host container]'}
                                </span>
                                {codebase.git_url && (
                                  <span className="text-[10px] text-sky-500/80 truncate">
                                    {codebase.git_url.replace('https://github.com/', 'gh:')}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="py-3 px-6 text-right font-sans">
                              {isWeb && svc.url ? (
                                <div className="flex items-center justify-end gap-1.5">
                                  <a
                                    href={svc.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300 font-mono text-xs underline underline-offset-2"
                                  >
                                    {svc.url}
                                    <ExternalLink className="w-3 h-3" />
                                  </a>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 text-muted-foreground hover:text-slate-100"
                                    onClick={() => onCopy && onCopy(svc.url)}
                                  >
                                    <Copy className="w-3 h-3" />
                                  </Button>
                                </div>
                              ) : (
                                <span className="inline-flex items-center gap-1 text-muted-foreground text-xs font-mono">
                                  <Lock className="w-3 h-3" />
                                  [INTERNAL ONLY]
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
