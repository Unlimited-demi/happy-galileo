import React from 'react';
import { Server, Cpu, Globe, AlertTriangle, ExternalLink, Copy, Lock, Database } from 'lucide-react';
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

            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted/20 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50">
                    <tr>
                      <th className="py-3 px-6">Service Name</th>
                      <th className="py-3 px-6">Type</th>
                      <th className="py-3 px-6">Port</th>
                      <th className="py-3 px-6">Container State</th>
                      <th className="py-3 px-6">Workspace Directory</th>
                      <th className="py-3 px-6 text-right">Access Endpoint</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40 font-mono text-xs">
                    {services.length === 0 ? (
                      <tr>
                        <td colSpan="6" className="py-8 text-center text-muted-foreground font-sans">
                          No active services discovered on this node.
                        </td>
                      </tr>
                    ) : (
                      services.map((svc) => {
                        const isWeb = svc.container_type === 'web' || !!svc.url;
                        const isRunning = svc.status === 'RUNNING';
                        return (
                          <tr key={svc.name} className="hover:bg-muted/30 transition-colors">
                            <td className="py-3 px-6 font-semibold text-slate-200">{svc.name}</td>
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
                                  {svc.status || 'UNKNOWN'}
                                </span>
                              </div>
                            </td>
                            <td className="py-3 px-6 text-muted-foreground truncate max-w-xs" title={svc.workspace_dir}>
                              {svc.workspace_dir || '[host container]'}
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
