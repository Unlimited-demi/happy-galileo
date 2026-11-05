import React from 'react';
import { Server, Box, Activity, AlertTriangle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export function KpiMetrics({ totalNodes, totalContainers, totalServices, openIncidentsCount, metrics }) {
  const serverMetrics = metrics?.server || {};
  const loadAvg = serverMetrics.load_average || {};
  const memory = serverMetrics.memory || {};

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
      <Card className="border-border/40">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Nodes</span>
            <Server className="w-4 h-4 text-muted-foreground" />
          </div>
          <div className="text-2xl font-bold tabular-nums">{totalNodes}</div>
          <Badge variant="secondary" className="mt-1 text-[10px]">
            {totalContainers} containers
          </Badge>
        </CardContent>
      </Card>

      <Card className="border-border/40">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Services</span>
            <Activity className="w-4 h-4 text-muted-foreground" />
          </div>
          <div className="text-2xl font-bold tabular-nums">{totalServices}</div>
          <Badge variant="outline" className="mt-1 text-[10px]">
            monitored
          </Badge>
        </CardContent>
      </Card>

      <Card className="border-border/40">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Load</span>
            <Box className="w-4 h-4 text-muted-foreground" />
          </div>
          {(() => {
            const cores = serverMetrics.cpu_cores || 0;
            const load5 = loadAvg['5min'] || 0;
            const pct = cores > 0 ? ((load5 / cores) * 100) : null;
            const network = serverMetrics.network || {};
            const rxRate = network.rx_rate_human || (network.rx_kbps ? `${network.rx_kbps} kbps` : null);
            const txRate = network.tx_rate_human || (network.tx_kbps ? `${network.tx_kbps} kbps` : null);
            const memPct = memory.usage_percent !== undefined ? `${Math.round(memory.usage_percent)}%` : null;

            return (
              <>
                <div className="text-2xl font-bold tabular-nums flex items-baseline justify-between">
                  <span>{pct !== null ? `${pct.toFixed(0)}%` : '—'}</span>
                  {memPct && (
                    <span className="text-xs font-mono font-normal text-muted-foreground">
                      RAM: <strong className="text-slate-200">{memPct}</strong>
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-muted-foreground mt-1 font-mono">
                  {loadAvg['1min']?.toFixed(2) || '0'} / {load5.toFixed(2)} / {loadAvg['15min']?.toFixed(2) || '0'}
                  {cores > 0 ? ` (${cores} c)` : ''}
                </div>
                {(rxRate || txRate) && (
                  <div className="text-[10px] text-sky-400 mt-1 font-mono flex items-center gap-2">
                    <span>↓ {rxRate || '0 kbps'}</span>
                    <span className="text-muted-foreground">•</span>
                    <span>↑ {txRate || '0 kbps'}</span>
                  </div>
                )}
              </>
            );
          })()}
        </CardContent>
      </Card>

      <Card className={`border-border/40 ${openIncidentsCount > 0 ? 'border-destructive/40' : ''}`}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Incidents</span>
            <AlertTriangle className={`w-4 h-4 ${openIncidentsCount > 0 ? 'text-destructive' : 'text-muted-foreground'}`} />
          </div>
          <div className={`text-2xl font-bold tabular-nums ${openIncidentsCount > 0 ? 'text-destructive' : ''}`}>
            {openIncidentsCount}
          </div>
          <Badge
            variant={openIncidentsCount > 0 ? 'destructive' : 'secondary'}
            className="mt-1 text-[10px]"
          >
            {openIncidentsCount > 0 ? 'active' : 'clear'}
          </Badge>
        </CardContent>
      </Card>
    </div>
  );
}
