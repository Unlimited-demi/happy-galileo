import React, { useState, useEffect, useMemo } from 'react';
import { Server, Globe, AlertTriangle, FileText } from 'lucide-react';
import { Navbar } from '@/components/Navbar';
import { KpiMetrics } from '@/components/KpiMetrics';
import { FleetMatrixView } from '@/components/FleetMatrixView';
import { ServiceDirectoryView } from '@/components/ServiceDirectoryView';
import { IncidentConsoleView } from '@/components/IncidentConsoleView';
import { IncidentModal } from '@/components/IncidentModal';
import { HealthDigestView } from '@/components/HealthDigestView';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

export function App() {
  const [status, setStatus] = useState({ services: [], total_containers: 0, open_incidents_count: 0 });
  const [fleet, setFleet] = useState({ nodes: [] });
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [activeTab, setActiveTab] = useState('fleet');
  const [serviceFilter, setServiceFilter] = useState('all');
  const [toast, setToast] = useState(null);

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const fetchData = async () => {
    try {
      const [sRes, fRes, iRes] = await Promise.all([
        fetch('/api/status').then((r) => r.json()),
        fetch('/api/fleet/nodes').then((r) => r.json()),
        fetch('/api/incidents?all=true').then((r) => r.json()),
      ]);
      if (sRes && !sRes.error) setStatus(sRes);
      if (fRes && fRes.nodes) setFleet(fRes);
      if (iRes && iRes.incidents) setIncidents(iRes.incidents);
    } catch (err) {
      console.error('Fetch error:', err);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 4000);
    return () => clearInterval(interval);
  }, []);

  const nodes = fleet.nodes || [];
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

  const handleDispatch = async (incId) => {
    try {
      showToast('🚀 Dispatching OpenCode worker...');
      const res = await fetch(`/api/incidents/${incId}/dispatch`, { method: 'POST' }).then((r) => r.json());
      if (res.success) {
        showToast(`⚡ OpenCode dispatched for ${res.fix_branch || incId}!`);
        fetchData();
      } else {
        showToast(`⚠️ Dispatch: ${res.message || res.error || 'Failed'}`);
      }
    } catch (e) {
      showToast(`⚠️ Network error: ${e.message}`);
    }
  };

  const handlePurge = async () => {
    try {
      showToast('🧹 Purging test incident dossiers...');
      const res = await fetch('/api/incidents/purge', { method: 'POST' }).then((r) => r.json());
      showToast(`✓ Cleared ${res.deleted_files || 0} incident dossier(s).`);
      fetchData();
    } catch (e) {
      showToast(`⚠️ Purge error: ${e.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black selection:bg-sky-500/30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Navbar baseDomain={status.base_domain} onRefresh={fetchData} />

      <KpiMetrics
        totalNodes={nodes.length > 0 ? nodes.length : 1}
        totalContainers={totalContainers}
        totalServices={totalServices}
        openIncidentsCount={openIncidentsCount}
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
          <FleetMatrixView nodes={nodes.length > 0 ? nodes : [status]} onCopy={showToast} />
        </TabsContent>

        <TabsContent value="services" className="mt-0">
          <ServiceDirectoryView
            nodes={nodes.length > 0 ? nodes : [status]}
            filter={serviceFilter}
            setFilter={setServiceFilter}
            onCopy={showToast}
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
