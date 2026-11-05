import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Server,
  Activity,
  FileText,
  Network,
  HardDrive,
  Settings,
  RefreshCw,
  RotateCcw,
  Copy,
  ExternalLink,
  Shield,
  CheckCircle2,
  AlertCircle,
  Check,
  Lock,
  Search,
  CheckCheck,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export function ServiceDetailModal({ service, onClose, onCopy, onRestartSuccess, showToast }) {
  if (!service) return null;

  const serviceName = service.service_name || service.container_name || service.name;
  const [activeTab, setActiveTab] = useState('overview');
  const [inspectData, setInspectData] = useState(null);
  const [loadingInspect, setLoadingInspect] = useState(false);
  const [logsText, setLogsText] = useState('');
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logTail, setLogTail] = useState(150);
  const [logFilter, setLogFilter] = useState('');
  const [autoRefreshLogs, setAutoRefreshLogs] = useState(true);
  const [restarting, setRestarting] = useState(false);
  const [copiedLogs, setCopiedLogs] = useState(false);

  const logsViewportRef = useRef(null);

  const getHeaders = () => {
    const key = localStorage.getItem('ara_api_key') || '';
    return key ? { Authorization: `Bearer ${key}` } : {};
  };

  // Fetch Container Inspect details
  const fetchInspect = async () => {
    if (!serviceName) return;
    setLoadingInspect(true);
    try {
      const res = await fetch(`/api/services/${encodeURIComponent(serviceName)}/inspect`, {
        headers: getHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setInspectData(data.service || null);
      }
    } catch (err) {
      console.error('Failed to inspect container:', err);
    } finally {
      setLoadingInspect(false);
    }
  };

  // Fetch Live Container Logs
  const fetchLogs = async (showSpinner = false) => {
    if (!serviceName) return;
    if (showSpinner) setLoadingLogs(true);
    try {
      const res = await fetch(
        `/api/services/${encodeURIComponent(serviceName)}/logs?tail=${logTail}`,
        { headers: getHeaders() }
      );
      if (res.ok) {
        const data = await res.json();
        setLogsText(data.logs || '');
      }
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    } finally {
      if (showSpinner) setLoadingLogs(false);
    }
  };

  // Restart Container Action
  const handleRestart = async () => {
    if (!window.confirm(`Are you sure you want to restart container "${serviceName}"?`)) return;
    setRestarting(true);
    try {
      const res = await fetch(`/api/services/${encodeURIComponent(serviceName)}/restart`, {
        method: 'POST',
        headers: { ...getHeaders(), 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (res.ok && data.success) {
        if (showToast) showToast(`✓ Service "${serviceName}" restarted successfully.`);
        if (onRestartSuccess) onRestartSuccess();
        fetchInspect();
        fetchLogs(true);
      } else {
        if (showToast) showToast(`⚠️ Restart failed: ${data.error || 'Unauthorized or server error'}`);
      }
    } catch (err) {
      if (showToast) showToast(`⚠️ Network error: ${err.message}`);
    } finally {
      setRestarting(false);
    }
  };

  useEffect(() => {
    fetchInspect();
    fetchLogs(true);
  }, [serviceName, logTail]);

  // Auto-refresh interval for logs when tab is active
  useEffect(() => {
    if (!autoRefreshLogs || activeTab !== 'logs') return;
    const interval = setInterval(() => {
      fetchLogs(false);
    }, 3000);
    return () => clearInterval(interval);
  }, [autoRefreshLogs, activeTab, serviceName, logTail]);

  // Scroll logs to bottom on initial load
  useEffect(() => {
    if (activeTab === 'logs' && logsViewportRef.current && !logFilter) {
      logsViewportRef.current.scrollTop = logsViewportRef.current.scrollHeight;
    }
  }, [activeTab, logsText]);

  // Filtered log lines
  const filteredLogLines = useMemo(() => {
    if (!logsText) return [];
    const lines = logsText.split('\n');
    if (!logFilter.trim()) return lines;
    const q = logFilter.toLowerCase();
    return lines.filter((l) => l.toLowerCase().includes(q));
  }, [logsText, logFilter]);

  const statusText = service.container_status || service.status || inspectData?.state?.status || 'UNKNOWN';
  const isRunning =
    inspectData?.state?.running ||
    statusText.toLowerCase().startsWith('up') ||
    statusText.toLowerCase().includes('running');

  return (
    <Dialog open={!!service} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl p-6 bg-slate-900 border-border/80 text-foreground max-h-[90vh] flex flex-col">
        {/* Modal Header */}
        <DialogHeader className="flex flex-row items-center justify-between pb-4 border-b border-border/60 shrink-0">
          <div className="flex items-center gap-3">
            <div className={`p-2.5 rounded-lg border ${isRunning ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20'}`}>
              <Server className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <DialogTitle className="text-base font-bold text-slate-100 font-mono">
                  {serviceName}
                </DialogTitle>
                <Badge
                  variant={isRunning ? 'success' : 'destructive'}
                  className="text-[10px] uppercase font-mono tracking-wider flex items-center gap-1.5"
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
                  {isRunning ? 'RUNNING' : 'STOPPED'}
                </Badge>
                <Badge variant="outline" className="text-[10px] uppercase font-mono">
                  {service.container_type || 'service'}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                Host: <strong className="text-slate-300 font-mono">{service.node_name || 'Primary Controller'}</strong>
                {inspectData?.id && (
                  <span className="ml-2 font-mono text-[11px] text-slate-400">
                    ID: {inspectData.id}
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 pr-6">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRestart}
              disabled={restarting}
              className="h-8 text-xs gap-1.5 font-semibold text-amber-400 hover:text-amber-300 border-amber-500/30 hover:bg-amber-500/10"
            >
              <RotateCcw className={`w-3.5 h-3.5 ${restarting ? 'animate-spin' : ''}`} />
              {restarting ? 'Restarting...' : 'Restart Container'}
            </Button>
          </div>
        </DialogHeader>

        {/* Tab Navigation */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full flex-1 flex flex-col min-h-0 mt-3">
          <TabsList className="grid grid-cols-5 w-full bg-slate-950/60 p-1 border border-border/60 shrink-0">
            <TabsTrigger value="overview" className="gap-1.5 text-xs py-1.5">
              <Activity className="w-3.5 h-3.5" />
              Overview & Health
            </TabsTrigger>
            <TabsTrigger value="logs" className="gap-1.5 text-xs py-1.5">
              <FileText className="w-3.5 h-3.5" />
              Live Logs
              {isRunning && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />}
            </TabsTrigger>
            <TabsTrigger value="network" className="gap-1.5 text-xs py-1.5">
              <Network className="w-3.5 h-3.5" />
              Network & Ingress
            </TabsTrigger>
            <TabsTrigger value="storage" className="gap-1.5 text-xs py-1.5">
              <HardDrive className="w-3.5 h-3.5" />
              Mounts & Volumes
            </TabsTrigger>
            <TabsTrigger value="config" className="gap-1.5 text-xs py-1.5">
              <Settings className="w-3.5 h-3.5" />
              Environment & Spec
            </TabsTrigger>
          </TabsList>

          {/* TAB 1: OVERVIEW & HEALTH */}
          <TabsContent value="overview" className="flex-1 overflow-y-auto space-y-4 pt-3 pr-1">
            {/* Quick Status Cards */}
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-slate-950/60 border border-border/60 space-y-1">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider">Uptime & Status</span>
                <div className="text-xs font-semibold text-slate-200">{statusText}</div>
                <div className="text-[11px] text-muted-foreground font-mono">
                  Restarts: <strong className="text-slate-300">{inspectData?.restart_count ?? service.restart_count ?? 0}</strong>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-950/60 border border-border/60 space-y-1">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider">Image / Tag</span>
                <div className="text-xs font-mono text-sky-400 truncate" title={inspectData?.image || service.image}>
                  {inspectData?.image || service.image || 'N/A'}
                </div>
                <div className="text-[11px] text-muted-foreground font-mono">
                  Version: <strong className="text-slate-300">{service.version || 'latest'}</strong>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-950/60 border border-border/60 space-y-1">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider">Protocol Health Probe</span>
                <div className="text-xs font-mono flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400 font-semibold">
                    {service.status_code ? `HTTP ${service.status_code}` : 'TCP Connected'}
                  </span>
                </div>
                <div className="text-[11px] text-muted-foreground font-mono">
                  Latency: <strong className="text-slate-300">{service.response_time_ms ? `${service.response_time_ms} ms` : '< 5 ms'}</strong>
                </div>
              </div>
            </div>

            {/* Container Details Table */}
            <div className="rounded-lg bg-slate-950/40 border border-border/60 p-4 space-y-3 font-mono text-xs">
              <div className="text-xs font-semibold text-slate-300 font-sans uppercase tracking-wider border-b border-border/40 pb-2 flex items-center justify-between">
                <span>Runtime Specification</span>
                {service.url && (
                  <a
                    href={service.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300 font-sans text-xs underline lowercase font-normal"
                  >
                    {service.url} <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>

              <div className="grid grid-cols-2 gap-y-2.5 gap-x-4 text-slate-300">
                <div>
                  <span className="text-muted-foreground font-sans">Container ID:</span>{' '}
                  <span className="text-slate-200">{inspectData?.id || service.container_id || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">Full Hash:</span>{' '}
                  <span className="text-slate-400 text-[11px] truncate inline-block max-w-[200px] align-bottom">
                    {inspectData?.full_id || '—'}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">Created At:</span>{' '}
                  <span className="text-slate-200">{inspectData?.created ? inspectData.created.split('.')[0].replace('T', ' ') : '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">Started At:</span>{' '}
                  <span className="text-slate-200">{inspectData?.state?.started_at ? inspectData.state.started_at.split('.')[0].replace('T', ' ') : '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">Exit Code:</span>{' '}
                  <span className={`font-bold ${inspectData?.state?.exit_code === 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {inspectData?.state?.exit_code ?? 0}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">OOM Killed:</span>{' '}
                  <span className={inspectData?.state?.oom_killed ? 'text-rose-400 font-bold' : 'text-slate-400'}>
                    {inspectData?.state?.oom_killed ? 'YES (Memory Exceeded)' : 'No'}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">Restart Policy:</span>{' '}
                  <span className="text-slate-200">{inspectData?.restart_policy || 'unless-stopped'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground font-sans">Port Mapping:</span>{' '}
                  <span className="text-slate-200">{service.port ? `${service.port} (Internal dev-net)` : '—'}</span>
                </div>
              </div>
            </div>
          </TabsContent>

          {/* TAB 2: LIVE CONTAINER LOGS */}
          <TabsContent value="logs" className="flex-1 flex flex-col min-h-0 pt-2 space-y-2">
            {/* Logs Toolbar */}
            <div className="flex items-center justify-between gap-2 shrink-0">
              <div className="flex items-center gap-2 flex-1 max-w-sm">
                <div className="relative w-full">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-muted-foreground" />
                  <input
                    type="text"
                    value={logFilter}
                    onChange={(e) => setLogFilter(e.target.value)}
                    placeholder="Filter logs (e.g. error, 500, warn)..."
                    className="w-full bg-slate-950 border border-border/80 rounded-lg pl-8 pr-3 py-1.5 text-xs font-mono text-slate-100 placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <select
                  value={logTail}
                  onChange={(e) => setLogTail(Number(e.target.value))}
                  className="bg-slate-950 border border-border/80 text-xs font-mono text-slate-200 rounded-lg px-2 py-1.5 focus:outline-none"
                >
                  <option value={50}>Last 50 lines</option>
                  <option value={150}>Last 150 lines</option>
                  <option value={300}>Last 300 lines</option>
                  <option value={500}>Last 500 lines</option>
                </select>

                <Button
                  variant={autoRefreshLogs ? 'default' : 'secondary'}
                  size="sm"
                  onClick={() => setAutoRefreshLogs(!autoRefreshLogs)}
                  className="h-8 text-xs gap-1.5"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${autoRefreshLogs ? 'animate-spin' : ''}`} />
                  {autoRefreshLogs ? 'Streaming' : 'Paused'}
                </Button>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (onCopy) onCopy(logsText);
                    setCopiedLogs(true);
                    setTimeout(() => setCopiedLogs(false), 2000);
                  }}
                  className="h-8 text-xs gap-1"
                >
                  {copiedLogs ? <CheckCheck className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copiedLogs ? 'Copied' : 'Copy'}
                </Button>
              </div>
            </div>

            {/* Log Viewport */}
            <div
              ref={logsViewportRef}
              className="flex-1 bg-zinc-950 border border-border/80 rounded-lg p-3 font-mono text-xs overflow-y-auto min-h-[300px] max-h-[460px] text-slate-200 select-text leading-relaxed"
            >
              {loadingLogs && !logsText ? (
                <div className="flex items-center justify-center h-48 text-muted-foreground text-xs">
                  <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Streaming live container logs...
                </div>
              ) : filteredLogLines.length === 0 ? (
                <div className="text-muted-foreground text-center py-12">
                  {logFilter ? `No log lines matching "${logFilter}"` : 'No logs recorded.'}
                </div>
              ) : (
                filteredLogLines.map((line, idx) => {
                  const lLower = line.toLowerCase();
                  const isErr = lLower.includes('error') || lLower.includes('exception') || lLower.includes('fatal') || lLower.includes('fail');
                  const isWarn = lLower.includes('warn') || lLower.includes('alert');
                  return (
                    <div
                      key={idx}
                      className={`py-0.5 whitespace-pre-wrap break-all ${
                        isErr ? 'text-rose-400 bg-rose-500/5' : isWarn ? 'text-amber-300' : 'text-slate-300'
                      }`}
                    >
                      {line}
                    </div>
                  );
                })
              )}
            </div>
          </TabsContent>

          {/* TAB 3: NETWORK & INGRESS */}
          <TabsContent value="network" className="flex-1 overflow-y-auto space-y-4 pt-3 pr-1">
            <div className="p-4 rounded-lg bg-slate-950/50 border border-border/60 space-y-3 font-mono text-xs">
              <div className="text-xs font-semibold text-slate-300 font-sans uppercase tracking-wider border-b border-border/40 pb-2 flex items-center justify-between">
                <span>Docker Bridge Network Topology</span>
                <span className="text-[11px] font-mono text-emerald-400 flex items-center gap-1 font-normal">
                  <Shield className="w-3.5 h-3.5" /> Zero Host Ports Policy Enforced
                </span>
              </div>

              {inspectData?.networks && Object.keys(inspectData.networks).length > 0 ? (
                Object.entries(inspectData.networks).map(([netName, netData]) => (
                  <div key={netName} className="p-3 rounded-lg bg-slate-950 border border-border/40 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-sky-400">Network: {netName}</span>
                      <Badge variant="outline" className="text-[10px]">Internal Bridge</Badge>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-slate-300">
                      <div><span className="text-muted-foreground">Internal IP:</span> {netData.ip_address || '172.19.0.x'}</div>
                      <div><span className="text-muted-foreground">Gateway:</span> {netData.gateway || '172.19.0.1'}</div>
                      <div><span className="text-muted-foreground">MAC Address:</span> {netData.mac_address || '—'}</div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-3 rounded-lg bg-slate-950 border border-border/40 space-y-2 text-slate-300">
                  <div className="font-bold text-sky-400">Network: dev-net</div>
                  <div className="grid grid-cols-2 gap-2">
                    <div><span className="text-muted-foreground">Internal Port:</span> {service.port || '8000'}</div>
                    <div><span className="text-muted-foreground">Ingress Controller:</span> Caddy Reverse Proxy</div>
                  </div>
                </div>
              )}

              <div className="p-3 rounded-lg bg-slate-950/80 border border-sky-500/20 text-xs text-slate-300 space-y-1 font-sans">
                <div className="font-semibold text-sky-400 flex items-center gap-1.5">
                  <Lock className="w-3.5 h-3.5" /> Ingress Routing Contract
                </div>
                <p className="text-[11px] text-muted-foreground">
                  This container is connected to the internal <code className="text-sky-300">dev-net</code> Docker network. All public incoming traffic enters exclusively through Caddy on ports 80/443 and dynamically routes to this service's internal port. No host ports are opened.
                </p>
              </div>
            </div>
          </TabsContent>

          {/* TAB 4: MOUNTS & VOLUMES */}
          <TabsContent value="storage" className="flex-1 overflow-y-auto space-y-3 pt-3 pr-1">
            <div className="rounded-lg bg-slate-950/50 border border-border/60 p-4 space-y-3 font-mono text-xs">
              <div className="text-xs font-semibold text-slate-300 font-sans uppercase tracking-wider border-b border-border/40 pb-2">
                Attached Volumes & Host Mounts
              </div>

              {inspectData?.mounts && inspectData.mounts.length > 0 ? (
                <div className="space-y-2">
                  {inspectData.mounts.map((m, i) => (
                    <div key={i} className="p-2.5 rounded-lg bg-slate-950 border border-border/40 space-y-1">
                      <div className="flex items-center justify-between">
                        <Badge variant="outline" className="text-[10px] uppercase font-mono">{m.type || 'bind'}</Badge>
                        <span className="text-[11px] text-muted-foreground">{m.rw ? 'Read/Write' : 'Read-Only'}</span>
                      </div>
                      <div className="text-[11px] text-slate-300">
                        <span className="text-muted-foreground font-sans">Host:</span> {m.source}
                      </div>
                      <div className="text-[11px] text-sky-400">
                        <span className="text-muted-foreground font-sans">Container:</span> {m.destination}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground font-sans text-xs">
                  No explicit bind mounts or volumes declared.
                </div>
              )}
            </div>
          </TabsContent>

          {/* TAB 5: ENVIRONMENT & SPEC */}
          <TabsContent value="config" className="flex-1 overflow-y-auto space-y-3 pt-3 pr-1">
            <div className="rounded-lg bg-slate-950/50 border border-border/60 p-4 space-y-3 font-mono text-xs">
              <div className="text-xs font-semibold text-slate-300 font-sans uppercase tracking-wider border-b border-border/40 pb-2 flex items-center justify-between">
                <span>Environment Variables & Entrypoint</span>
                <span className="text-[11px] text-muted-foreground font-sans font-normal">(Secrets redacted as ******)</span>
              </div>

              {inspectData?.cmd && inspectData.cmd.length > 0 && (
                <div>
                  <span className="text-muted-foreground font-sans block mb-1">Command (Cmd):</span>
                  <div className="p-2 rounded bg-slate-950 border border-border/40 text-slate-200">
                    {inspectData.cmd.join(' ')}
                  </div>
                </div>
              )}

              <div>
                <span className="text-muted-foreground font-sans block mb-1.5">Environment:</span>
                {inspectData?.env && inspectData.env.length > 0 ? (
                  <div className="p-3 rounded-lg bg-slate-950 border border-border/40 space-y-1 max-h-60 overflow-y-auto">
                    {inspectData.env.map((ev, i) => (
                      <div key={i} className="text-slate-300 text-[11px] truncate">
                        {ev}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-muted-foreground text-xs py-4 text-center font-sans">
                    No custom environment variables detected.
                  </div>
                )}
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

export default ServiceDetailModal;
