import React, { useMemo } from 'react';
import { ExternalLink, Copy, Lock, Github, GitBranch } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export function ServiceDirectoryView({ nodes, filter, setFilter, onCopy, onSelectService }) {
  const allServices = useMemo(() => {
    const list = [];
    nodes.forEach((n) => {
      (n.services || []).forEach((s) => {
        list.push({ ...s, node_name: n.node_name || 'Primary Controller' });
      });
    });
    return list;
  }, [nodes]);

  const filteredServices = useMemo(() => {
    if (filter === 'all') return allServices;
    if (filter === 'web') return allServices.filter((s) => s.container_type === 'web' || !!s.url);
    if (filter === 'db') return allServices.filter((s) => s.container_type === 'database' || s.container_type === 'cache');
    if (filter === 'mail') return allServices.filter((s) => s.container_type === 'mail');
    return allServices;
  }, [allServices, filter]);

  return (
    <div className="space-y-4">
      {/* Sub Filter Buttons */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {[
            { id: 'all', label: 'All Services' },
            { id: 'web', label: 'Web & APIs' },
            { id: 'db', label: 'Databases & Caches' },
            { id: 'mail', label: 'Mail Infrastructure' },
          ].map((btn) => (
            <Button
              key={btn.id}
              variant={filter === btn.id ? 'default' : 'secondary'}
              size="sm"
              onClick={() => setFilter(btn.id)}
              className="text-xs h-8"
            >
              {btn.label}
            </Button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground hidden sm:inline">
          💡 Click any service row to view runtime inspection & live logs
        </span>
      </div>

      <Card className="border-border/80 overflow-hidden">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/20 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50">
                <tr>
                  <th className="py-3 px-6">Service Name</th>
                  <th className="py-3 px-6">Host Node</th>
                  <th className="py-3 px-6">Type</th>
                  <th className="py-3 px-6">Port</th>
                  <th className="py-3 px-6">Status</th>
                  <th className="py-3 px-6">Repository</th>
                  <th className="py-3 px-6 text-right">Access / Logs</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40 font-mono text-xs">
                {filteredServices.length === 0 ? (
                  <tr>
                    <td colSpan="7" className="py-8 text-center text-muted-foreground font-sans">
                      No matching services found.
                    </td>
                  </tr>
                ) : (
                  filteredServices.map((svc, i) => {
                    const isWeb = svc.container_type === 'web' || !!svc.url;
                    const statusText = svc.container_status || svc.status || 'UNKNOWN';
                    const sLower = statusText.toLowerCase();
                    const isRunning = sLower.startsWith('up') || sLower.includes('running') || sLower === 'active';
                    return (
                      <tr
                        key={`${svc.service_name || svc.name}-${i}`}
                        onClick={() => onSelectService && onSelectService(svc)}
                        className="hover:bg-slate-800/40 cursor-pointer transition-colors group"
                      >
                        <td className="py-3 px-6 font-semibold text-slate-200 group-hover:text-sky-400 transition-colors">
                          <div className="flex items-center gap-2">
                            <span>{svc.service_name || svc.container_name || svc.name}</span>
                          </div>
                        </td>
                        <td className="py-3 px-6 font-sans text-muted-foreground">{svc.node_name}</td>
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
                        <td className="py-3 px-6 font-sans">
                          {svc.git_url ? (
                            <a
                              href={svc.git_url}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/80 hover:bg-slate-700/80 text-sky-400 hover:text-sky-300 border border-slate-700/60 font-mono text-[11px] transition-colors max-w-[160px] truncate"
                              title={`${svc.git_url} (${svc.git_branch || 'master'})`}
                            >
                              <Github className="w-3.5 h-3.5 text-slate-300 shrink-0" />
                              <span className="truncate">{svc.repo_name || svc.git_url.split('/').slice(-2).join('/')}</span>
                              <ExternalLink className="w-2.5 h-2.5 text-slate-400 shrink-0" />
                            </a>
                          ) : (
                            <span className="text-muted-foreground text-xs font-mono">—</span>
                          )}
                        </td>
                        <td className="py-3 px-6 text-right font-sans">
                          <div className="flex items-center justify-end gap-2">
                            {isWeb && svc.url ? (
                              <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
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
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    if (onCopy) onCopy(svc.url);
                                  }}
                                >
                                  <Copy className="w-3 h-3" />
                                </Button>
                              </div>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-muted-foreground text-xs font-mono mr-2">
                                <Lock className="w-3 h-3" />
                                [INTERNAL]
                              </span>
                            )}
                            <Button
                              variant="secondary"
                              size="sm"
                              className="h-6 text-[11px] px-2 gap-1 text-slate-300 group-hover:bg-sky-500/10 group-hover:text-sky-400 group-hover:border group-hover:border-sky-500/20"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (onSelectService) onSelectService(svc);
                              }}
                            >
                              Inspect & Logs
                            </Button>
                          </div>
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
    </div>
  );
}
