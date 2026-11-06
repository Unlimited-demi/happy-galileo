import React, { useState, useEffect, useMemo } from 'react';
import { Server, Globe, AlertTriangle, FileText } from 'lucide-react';
import { Navbar } from '@/components/Navbar';
import { KpiMetrics } from '@/components/KpiMetrics';
import { FleetMatrixView } from '@/components/FleetMatrixView';
import { ServiceDirectoryView } from '@/components/ServiceDirectoryView';
import { IncidentConsoleView } from '@/components/IncidentConsoleView';
import { IncidentModal } from '@/components/IncidentModal';
import { ServiceDetailModal } from '@/components/ServiceDetailModal';
import { HealthDigestView } from '@/components/HealthDigestView';
import { AuthModal } from '@/components/AuthModal';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

export function App() {
  const [status, setStatus] = useState({ services: [], total_containers: 0, open_incidents_count: 0 });
  const [fleet, setFleet] = useState({ nodes: [] });
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [selectedService, setSelectedService] = useState(null);
  const [activeTab, setActiveTab] = useState('fleet');
  const [serviceFilter, setServiceFilter] = useState('all');
  const [toast, setToast] = useState(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [currentRole, setCurrentRole] = useState(null);

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const getAuthHeaders = () => {
    const key = localStorage.getItem('ara_api_key') || '';
    return key ? { Authorization: `Bearer ${key}` } : {};
  };

  const fetchData = async () => {
    try {
      const headers = getAuthHeaders();
      const [sRes, fRes, iRes] = await Promise.all([
        fetch('/api/status', { headers }).then((r) => r.json()),
        fetch('/api/fleet/nodes', { headers }).then((r) => r.json()),
        fetch('/api/incidents?all=true', { headers }).then((r) => r.json()),
      ]);
      if (sRes) {
        if (!sRes.error) {
          setStatus(sRes);
          if (sRes.current_role) setCurrentRole(sRes.current_role);
        } else if (sRes.error) {
          const errLower = sRes.error.toLowerCase();
          if (errLower.includes('auth') || errLower.includes('unauthorized') || errLower.includes('required')) {
            setCurrentRole('unauthorized');
            setAuthModalOpen(true);
          }
        }
      }
      if (fRes && fRes.nodes) setFleet(fRes);
      if (iRes && iRes.incidents) setIncidents(iRes.incidents);
    } catch (err) {
      console.error('Fetch error:', err);
    }
  };

  useEffect(() => {
    // Check if key or token is in URL query parameters
    let foundKey = false;
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const urlKey = urlParams.get('key') || urlParams.get('token');
      if (urlKey) {
        localStorage.setItem('ara_api_key', urlKey);
        showToast('🔑 API Key detected from URL');
        foundKey = true;
      }
    } catch (e) {}

    // Auto-prompt AuthModal immediately if no key is present in localStorage or URL
    if (!foundKey && !localStorage.getItem('ara_api_key')) {
      setAuthModalOpen(true);
    }

    fetchData();
    const interval = setInterval(fetchData, 4000);
    return () => clearInterval(interval);
  }, []);

  const nodes = useMemo(() => {
    const list = [...(fleet.nodes || [])];
    list.sort((a, b) => {
      const aName = a.node_name || '';
      const bName = b.node_name || '';
      if (aName === 'hub-vm') return -1;
      if (bName === 'hub-vm') return 1;
      return aName.localeCompare(bName);
    });
    return list;
  }, [fleet.nodes]);
  const totalContainers = useMemo(() => {
    if (nodes.length > 0) return nodes.reduce((acc, n) => acc + (n.containers_count || 0), 0);
    return status.total_containers || 0;
  }, [nodes, status]);

  const totalServices = useMemo(() => {
    if (nodes.length > 0) return nodes.reduce((acc, n) => acc + (n.services?.length || 0), 0);
    return status.services?.length || 0;
  }, [nodes, status]);

  const openIncidentsCount = useMemo(() => {
    if (nodes.length > 0) return nodes.reduce((acc, n) => acc + (n.open_incidents_count || 0), 0);
    return status.open_incidents_count || 0;
  }, [nodes, status]);

  // Aggregate metrics from all nodes (use hub node's metrics as primary display)
  const aggregatedMetrics = useMemo(() => {
    if (nodes.length > 0) {
      let total1min = 0, total5min = 0, total15min = 0, totalCores = 0;
      let totalMemUsed = 0, totalMemTotal = 0;
      nodes.forEach(n => {
        const raw = n.metrics || {};
        const sm = raw.server || raw;
        let la = sm.load_average || raw.load_average;
        if (!la || typeof la !== 'object' || (la['1min'] === undefined && la['5min'] === undefined)) {
          if (typeof raw.load_avg === 'string' && raw.load_avg.trim() && raw.load_avg !== 'N/A') {
            const parts = raw.load_avg.trim().split(/\s+/).map(Number);
            la = { '1min': parts[0] || 0, '5min': parts[1] || 0, '15min': parts[2] || 0 };
          } else {
            la = { '1min': 0, '5min': 0, '15min': 0 };
          }
        }
        total1min += la['1min'] || 0;
        total5min += la['5min'] || 0;
        total15min += la['15min'] || 0;
        totalCores += sm.cpu_cores || sm.cpu_count || raw.cpu_cores || 0;
        const mem = sm.memory || raw.memory || {};
        const memTot = mem.total_bytes || (raw.memory_total_mb ? raw.memory_total_mb * 1048576 : 0);
        const memUsed = mem.used_bytes || (raw.memory_used_mb ? raw.memory_used_mb * 1048576 : 0);
        totalMemUsed += memUsed;
        totalMemTotal += memTot;
      });
      if (totalCores > 0 || totalMemTotal > 0) {
        return {
          server: {
            cpu_cores: totalCores,
            load_average: { '1min': total1min, '5min': total5min, '15min': total15min },
            memory: {
              used_bytes: totalMemUsed,
              total_bytes: totalMemTotal,
              usage_percent: totalMemTotal > 0 ? ((totalMemUsed / totalMemTotal) * 100) : 0,
            },
          },
        };
      }
    }
    // Fallback to hub's own metrics
    return status.metrics || {};
  }, [nodes, status]);

  const handleDispatch = async (incId) => {
    try {
      showToast('🚀 Dispatching OpenCode worker...');
      const res = await fetch(`/api/incidents/${incId}/dispatch`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      }).then((r) => r.json());
      if (res.success) {
        showToast(`⚡ OpenCode dispatched for ${res.fix_branch || incId}!`);
        fetchData();
      } else if (res.status === 'PREPARED_NOT_DISPATCHED') {
        showToast(`📋 Dossier prepared! Launch via host terminal: devctl dispatch ${incId}`);
        fetchData();
      } else {
        if (res.error && res.error.toLowerCase().includes('permission')) {
          setAuthModalOpen(true);
        }
        showToast(`⚠️ Dispatch: ${res.message || res.error || 'Failed'}`);
      }
    } catch (e) {
      showToast(`⚠️ Network error: ${e.message}`);
    }
  };

  const handlePurge = async () => {
    try {
      showToast('🧹 Purging test incident dossiers...');
      const res = await fetch('/api/incidents/purge', {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      }).then((r) => r.json());
      if (res.error && res.error.toLowerCase().includes('permission')) {
        setAuthModalOpen(true);
        showToast(`⚠️ Admin permission required to purge incidents.`);
      } else {
        showToast(`✓ Cleared ${res.deleted_files || 0} incident dossier(s).`);
        fetchData();
      }
    } catch (e) {
      showToast(`⚠️ Purge error: ${e.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black selection:bg-sky-500/30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Navbar
        baseDomain={status.base_domain}
        onRefresh={fetchData}
        currentRole={currentRole}
        onOpenAuth={() => setAuthModalOpen(true)}
      />

      <KpiMetrics
        totalNodes={nodes.length > 0 ? nodes.length : 1}
        totalContainers={totalContainers}
        totalServices={totalServices}
        openIncidentsCount={openIncidentsCount}
        metrics={aggregatedMetrics}
      />

      {/* Main Tab View */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid grid-cols-4 w-full sm:w-auto sm:inline-grid">
          <TabsTrigger value="fleet" className="gap-2">
            <Server className="w-4 h-4" />
            Multi-Server Fleet
            <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-mono">
              {nodes.length > 0 ? nodes.length : 1}
            </span>
          </TabsTrigger>
          <TabsTrigger value="services" className="gap-2">
            <Globe className="w-4 h-4" />
            Service Directory
            <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-mono">
              {totalServices}
            </span>
          </TabsTrigger>
          <TabsTrigger value="incidents" className="gap-2">
            <AlertTriangle className="w-4 h-4" />
            Incident Console
            {openIncidentsCount > 0 ? (
              <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full bg-rose-500/20 text-rose-400 font-mono font-bold">
                {openIncidentsCount}
              </span>
            ) : (
              <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-mono">
                {incidents.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="reports" className="gap-2">
            <FileText className="w-4 h-4" />
            Ops Health Digest
          </TabsTrigger>
        </TabsList>

        <TabsContent value="fleet" className="mt-0">
          <FleetMatrixView
            nodes={nodes.length > 0 ? nodes : [status]}
            onCopy={showToast}
            onSelectService={setSelectedService}
          />
        </TabsContent>

        <TabsContent value="services" className="mt-0">
          <ServiceDirectoryView
            nodes={nodes.length > 0 ? nodes : [status]}
            filter={serviceFilter}
            setFilter={setServiceFilter}
            onCopy={showToast}
            onSelectService={setSelectedService}
          />
        </TabsContent>

        <TabsContent value="incidents" className="mt-0">
          <IncidentConsoleView
            incidents={incidents}
            onSelect={setSelectedIncident}
            onDispatch={handleDispatch}
            onPurge={handlePurge}
          />
        </TabsContent>

        <TabsContent value="reports" className="mt-0">
          <HealthDigestView nodes={nodes.length > 0 ? nodes : [status]} incidents={incidents} />
        </TabsContent>
      </Tabs>

      {/* Incident Modal Popup */}
      <IncidentModal
        incident={selectedIncident}
        onClose={() => setSelectedIncident(null)}
        onCopy={showToast}
        onDispatch={handleDispatch}
      />

      {/* Service Detail & Live Log Modal */}
      <ServiceDetailModal
        service={selectedService}
        onClose={() => setSelectedService(null)}
        onCopy={showToast}
        onRestartSuccess={fetchData}
        showToast={showToast}
      />

      {/* Auth & RBAC Key Modal */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        currentRole={currentRole}
        onKeySaved={(role) => {
          setCurrentRole(role);
          fetchData();
        }}
        showToast={showToast}
      />

      {/* Toast Notification */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-900 border border-border text-slate-100 text-xs px-4 py-2.5 rounded-lg shadow-2xl animate-in fade-in slide-in-from-bottom-3 duration-200">
          {toast}
        </div>
      )}
      </div>
    </div>
  );
}

export default App;
