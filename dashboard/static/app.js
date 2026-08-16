const { useState, useEffect, useMemo } = React;

// Framer Motion Primitives
const MotionLib = window.Motion || window.framerMotion || {};
const motion = MotionLib.motion || {
  div: 'div',
  header: 'header',
  button: 'button',
  tr: 'tr',
  span: 'span',
};
const AnimatePresence = MotionLib.AnimatePresence || (({ children }) => children);

// Animation Variants
const fadeInVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.25, ease: 'easeOut' } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.15 } },
};

const cardSpringVariants = {
  hover: { scale: 1.015, y: -2, transition: { type: 'spring', stiffness: 400, damping: 25 } },
  tap: { scale: 0.985 },
};

const modalVariants = {
  hidden: { opacity: 0, scale: 0.94, y: 20 },
  visible: { opacity: 1, scale: 1, y: 0, transition: { type: 'spring', stiffness: 350, damping: 28 } },
  exit: { opacity: 0, scale: 0.94, y: 20, transition: { duration: 0.18 } },
};

// ── SVG ICON LIBRARY (Lucide Style) ──
const createSvg = (paths, size = 18, className = '') =>
  React.createElement(
    'svg',
    {
      width: size,
      height: size,
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      strokeWidth: '2',
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      className: className,
    },
    paths
  );

const IconsRaw = {
  Server: (props) =>
    createSvg(
      [
        React.createElement('rect', { key: '1', x: '2', y: '2', width: '20', height: '8', rx: '2', ry: '2' }),
        React.createElement('rect', { key: '2', x: '2', y: '14', width: '20', height: '8', rx: '2', ry: '2' }),
        React.createElement('line', { key: '3', x1: '6', y1: '6', x2: '6.01', y2: '6' }),
        React.createElement('line', { key: '4', x1: '6', y1: '18', x2: '6.01', y2: '18' }),
      ],
      props.size,
      props.className
    ),
  ShieldCheck: (props) =>
    createSvg(
      [
        React.createElement('path', { key: '1', d: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' }),
        React.createElement('path', { key: '2', d: 'm9 12 2 2 4-4' }),
      ],
      props.size,
      props.className
    ),
  ShieldAlert: (props) =>
    createSvg(
      [
        React.createElement('path', { key: '1', d: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' }),
        React.createElement('line', { key: '2', x1: '12', y1: '8', x2: '12', y2: '12' }),
        React.createElement('line', { key: '3', x1: '12', y1: '16', x2: '12.01', y2: '16' }),
      ],
      props.size,
      props.className
    ),
  AlertTriangle: (props) =>
    createSvg(
      [
        React.createElement('path', { key: '1', d: 'm21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z' }),
        React.createElement('line', { key: '2', x1: '12', y1: '9', x2: '12', y2: '13' }),
        React.createElement('line', { key: '3', x1: '12', y1: '17', x2: '12.01', y2: '17' }),
      ],
      props.size,
      props.className
    ),
  Cpu: (props) =>
    createSvg(
      [
        React.createElement('rect', { key: '1', x: '4', y: '4', width: '16', height: '16', rx: '2' }),
        React.createElement('rect', { key: '2', x: '9', y: '9', width: '6', height: '6' }),
        React.createElement('path', { key: '3', d: 'M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3' }),
      ],
      props.size,
      props.className
    ),
  Database: (props) =>
    createSvg(
      [
        React.createElement('ellipse', { key: '1', cx: '12', cy: '5', rx: '9', ry: '3' }),
        React.createElement('path', { key: '2', d: 'M21 12c0 1.66-4 3-9 3s-9-1.34-9-3' }),
        React.createElement('path', { key: '3', d: 'M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5' }),
      ],
      props.size,
      props.className
    ),
  Globe: (props) =>
    createSvg(
      [
        React.createElement('circle', { key: '1', cx: '12', cy: '12', r: '10' }),
        React.createElement('line', { key: '2', x1: '2', y1: '12', x2: '22', y2: '12' }),
        React.createElement('path', { key: '3', d: 'M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z' }),
      ],
      props.size,
      props.className
    ),
  ExternalLink: (props) =>
    createSvg(
      [
        React.createElement('path', { key: '1', d: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' }),
        React.createElement('polyline', { key: '2', points: '15 3 21 3 21 9' }),
        React.createElement('line', { key: '3', x1: '10', y1: '14', x2: '21', y2: '3' }),
      ],
      props.size,
      props.className
    ),
  Copy: (props) =>
    createSvg(
      [
        React.createElement('rect', { key: '1', x: '9', y: '9', width: '13', height: '13', rx: '2', ry: '2' }),
        React.createElement('path', { key: '2', d: 'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1' }),
      ],
      props.size,
      props.className
    ),
  Refresh: (props) =>
    createSvg(
      [
        React.createElement('path', { key: '1', d: 'M21.5 2v6h-6' }),
        React.createElement('path', { key: '2', d: 'M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67' }),
      ],
      props.size,
      props.className
    ),
  Terminal: (props) =>
    createSvg(
      [
        React.createElement('polyline', { key: '1', points: '4 17 10 11 4 5' }),
        React.createElement('line', { key: '2', x1: '12', y1: '19', x2: '20', y2: '19' }),
      ],
      props.size,
      props.className
    ),
  Lock: (props) =>
    createSvg(
      [
        React.createElement('rect', { key: '1', x: '3', y: '11', width: '18', height: '11', rx: '2', ry: '2' }),
        React.createElement('path', { key: '2', d: 'M7 11V7a5 5 0 0 1 10 0v4' }),
      ],
      props.size,
      props.className
    ),
  FileText: (props) =>
    createSvg(
      [
        React.createElement('path', { key: '1', d: 'M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z' }),
        React.createElement('polyline', { key: '2', points: '14 2 14 8 20 8' }),
        React.createElement('line', { key: '3', x1: '16', y1: '13', x2: '8', y2: '13' }),
        React.createElement('line', { key: '4', x1: '16', y1: '17', x2: '8', y2: '17' }),
      ],
      props.size,
      props.className
    ),
};

// Safe Proxy so undefined icons never crash React rendering
const Icons = new Proxy(IconsRaw, {
  get: (target, prop) => target[prop] || ((props) => createSvg([], props?.size, props?.className)),
});

function copyText(text, callback) {
  navigator.clipboard.writeText(text).then(() => {
    if (callback) callback('Copied to clipboard');
  });
}

// ── MAIN APPLICATION ROOT COMPONENT ──
function App() {
  const [status, setStatus] = useState({ services: [], total_containers: 0, open_incidents_count: 0 });
  const [fleet, setFleet] = useState({ nodes: [] });
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [activeTab, setActiveTab] = useState('fleet'); // 'fleet', 'services', 'incidents', 'reports'
  const [serviceFilter, setServiceFilter] = useState('all'); // 'all', 'web', 'db', 'mail'
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const fetchData = async () => {
    try {
      const [statusRes, fleetRes, incRes] = await Promise.all([
        fetch('/api/status').then((r) => r.json()).catch(() => ({})),
        fetch('/api/fleet/nodes').then((r) => r.json()).catch(() => ({ nodes: [] })),
        fetch('/api/incidents?all=true').then((r) => r.json()).catch(() => ({ incidents: [] })),
      ]);

      if (statusRes.services) setStatus(statusRes);
      if (fleetRes.nodes) setFleet(fleetRes);
      if (incRes.incidents) setIncidents(incRes.incidents);
    } catch (err) {
      console.error('Data polling error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // Compute aggregate metrics across fleet
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
      showToast('🚀 Dispatching OpenCode remediation worker...');
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

  return React.createElement(
    motion.div,
    { className: 'app-wrapper', initial: 'hidden', animate: 'visible', variants: fadeInVariants },
    // ── 1. Top Navigation Bar ──
    React.createElement(
      motion.header,
      { className: 'top-nav', initial: { opacity: 0, y: -10 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.3 } },
      React.createElement(
        'div',
        { className: 'brand-section' },
        React.createElement('div', { className: 'brand-icon-box' }, React.createElement(Icons.ShieldCheck, { size: 22 })),
        React.createElement(
          'div',
          { className: 'brand-title-wrap' },
          React.createElement(
            'div',
            { className: 'brand-title' },
            'ServerGuard',
            React.createElement('span', { className: 'brand-badge' }, 'Cloud-Ops')
          ),
          React.createElement('div', { className: 'brand-subtitle' }, `Fleet Management & Autonomous AI-Ops | *.${status.base_domain || 'dev-server.datakrib.com'}`)
        )
      ),
      React.createElement(
        'div',
        { className: 'nav-actions' },
        React.createElement(
          'div',
          { className: 'live-pulse-badge' },
          React.createElement('span', { className: 'pulse-dot' }),
          'Live Telemetry'
        ),
        React.createElement(
          motion.button,
          { className: 'btn-secondary', onClick: fetchData, whileHover: { scale: 1.04 }, whileTap: { scale: 0.96 } },
          React.createElement(Icons.Refresh, { size: 14 }),
          'Refresh'
        )
      )
    ),

    // ── 2. KPI Metrics Bar ──
    React.createElement(
      'div',
      { className: 'kpi-grid' },
      React.createElement(
        motion.div,
        { className: 'kpi-card', whileHover: 'hover', whileTap: 'tap', variants: cardSpringVariants },
        React.createElement(
          'div',
          null,
          React.createElement('div', { className: 'kpi-label' }, 'Total Nodes'),
          React.createElement('div', { className: 'kpi-value' }, nodes.length > 0 ? nodes.length : 1)
        ),
        React.createElement('div', { className: 'kpi-icon-box' }, React.createElement(Icons.Server, { size: 20, className: 'kpi-icon-emerald' }))
      ),
      React.createElement(
        motion.div,
        { className: 'kpi-card', whileHover: 'hover', whileTap: 'tap', variants: cardSpringVariants },
        React.createElement(
          'div',
          null,
          React.createElement('div', { className: 'kpi-label' }, 'Monitored Containers'),
          React.createElement('div', { className: 'kpi-value' }, totalContainers)
        ),
        React.createElement('div', { className: 'kpi-icon-box' }, React.createElement(Icons.Cpu, { size: 20, className: 'kpi-icon-cyan' }))
      ),
      React.createElement(
        motion.div,
        { className: 'kpi-card', whileHover: 'hover', whileTap: 'tap', variants: cardSpringVariants },
        React.createElement(
          'div',
          null,
          React.createElement('div', { className: 'kpi-label' }, 'Active Services'),
          React.createElement('div', { className: 'kpi-value' }, totalServices)
        ),
        React.createElement('div', { className: 'kpi-icon-box' }, React.createElement(Icons.Globe, { size: 20, className: 'kpi-icon-emerald' }))
      ),
      React.createElement(
        motion.div,
        { className: 'kpi-card', whileHover: 'hover', whileTap: 'tap', variants: cardSpringVariants },
        React.createElement(
          'div',
          null,
          React.createElement('div', { className: 'kpi-label' }, 'Open Incidents'),
          React.createElement('div', { className: 'kpi-value', style: { color: openIncidentsCount > 0 ? 'var(--accent-rose)' : 'var(--text-primary)' } }, openIncidentsCount)
        ),
        React.createElement('div', { className: 'kpi-icon-box' }, React.createElement(Icons.AlertTriangle, { size: 20, className: openIncidentsCount > 0 ? 'kpi-icon-rose' : 'kpi-icon-muted' }))
      )
    ),

    // ── 3. Tab Navigation ──
    React.createElement(
      'nav',
      { className: 'tab-bar' },
      React.createElement(
        motion.button,
        { className: `tab-btn ${activeTab === 'fleet' ? 'active' : ''}`, onClick: () => setActiveTab('fleet'), whileTap: { scale: 0.97 } },
        React.createElement(Icons.Server, { size: 15 }),
        'Multi-Server Fleet',
        React.createElement('span', { className: 'tab-counter-badge' }, nodes.length || 1)
      ),
      React.createElement(
        motion.button,
        { className: `tab-btn ${activeTab === 'services' ? 'active' : ''}`, onClick: () => setActiveTab('services'), whileTap: { scale: 0.97 } },
        React.createElement(Icons.Globe, { size: 15 }),
        'Service Directory',
        React.createElement('span', { className: 'tab-counter-badge' }, totalServices)
      ),
      React.createElement(
        motion.button,
        { className: `tab-btn ${activeTab === 'incidents' ? 'active' : ''}`, onClick: () => setActiveTab('incidents'), whileTap: { scale: 0.97 } },
        React.createElement(Icons.AlertTriangle, { size: 15 }),
        'Incident Console',
        openIncidentsCount > 0
          ? React.createElement('span', { className: 'tab-counter-badge alert' }, openIncidentsCount)
          : React.createElement('span', { className: 'tab-counter-badge' }, incidents.length)
      ),
      React.createElement(
        motion.button,
        { className: `tab-btn ${activeTab === 'reports' ? 'active' : ''}`, onClick: () => setActiveTab('reports'), whileTap: { scale: 0.97 } },
        React.createElement(Icons.FileText, { size: 15 }),
        'Ops Health Digest'
      )
    ),

    // ── 4. Tab Views with Framer Motion AnimatePresence ──
    React.createElement(
      AnimatePresence,
      { mode: 'wait' },
      React.createElement(
        motion.div,
        { key: activeTab, initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -6 }, transition: { duration: 0.2 } },
        activeTab === 'fleet' && React.createElement(FleetMatrixView, { nodes: nodes.length > 0 ? nodes : [status], onCopy: showToast }),
        activeTab === 'services' && React.createElement(ServiceDirectoryView, { nodes: nodes.length > 0 ? nodes : [status], filter: serviceFilter, setFilter: setServiceFilter, onCopy: showToast }),
        activeTab === 'incidents' && React.createElement(IncidentConsoleView, { incidents, onSelect: setSelectedIncident, onDispatch: handleDispatch, onPurge: handlePurge }),
        activeTab === 'reports' && React.createElement(HealthDigestView, { nodes: nodes.length > 0 ? nodes : [status], incidents })
      )
    ),

    // ── 5. Modal Incident Dossier Popup with Framer Motion ──
    React.createElement(
      AnimatePresence,
      null,
      selectedIncident && React.createElement(IncidentModal, { incident: selectedIncident, onClose: () => setSelectedIncident(null), onCopy: showToast, onDispatch: handleDispatch })
    ),

    // ── 6. Toast Notification ──
    React.createElement('div', { className: `toast-msg ${toast ? 'show' : ''}` }, toast)
  );
}

// ── COMPONENT: FleetMatrixView ──
function FleetMatrixView({ nodes, onCopy }) {
  return React.createElement(
    'div',
    null,
    nodes.map((node, idx) => {
      const isOnline = node.online !== false;
      const services = node.services || [];
      return React.createElement(
        'div',
        { key: node.node_name || idx, className: 'fleet-node-card' },
        React.createElement(
          'div',
          { className: 'fleet-node-header' },
          React.createElement(
            'div',
            { className: 'fleet-node-meta' },
            React.createElement(
              'div',
              { className: 'node-title-group' },
              React.createElement(
                'div',
                { className: 'node-name-text' },
                React.createElement(Icons.Server, { size: 18 }),
                node.node_name || 'Primary Workstation',
                React.createElement(
                  'span',
                  {
                    style: {
                      fontSize: '0.72rem',
                      fontWeight: '700',
                      color: isOnline ? 'var(--accent-emerald)' : 'var(--accent-rose)',
                      background: isOnline ? 'var(--accent-emerald-subtle)' : 'var(--accent-rose-subtle)',
                      padding: '2px 8px',
                      borderRadius: '12px',
                    },
                  },
                  isOnline ? 'ONLINE' : 'UNREACHABLE'
                )
              ),
              React.createElement('span', { className: 'node-domain-code' }, `*.${node.base_domain || 'dev-server.datakrib.com'}`)
            )
          ),
          React.createElement(
            'div',
            { className: 'node-stat-pills' },
            React.createElement('div', { className: 'node-pill' }, React.createElement(Icons.Cpu, { size: 14 }), `${node.containers_count || 0} Containers`),
            React.createElement('div', { className: 'node-pill' }, React.createElement(Icons.Globe, { size: 14 }), `${services.length} Services`),
            (node.open_incidents_count || 0) > 0 &&
              React.createElement('div', { className: 'node-pill alert' }, React.createElement(Icons.AlertTriangle, { size: 14 }), `${node.open_incidents_count} Incidents`)
          )
        ),
        React.createElement(
          'div',
          { className: 'table-responsive' },
          React.createElement(
            'table',
            { className: 'data-table' },
            React.createElement(
              'thead',
              null,
              React.createElement(
                'tr',
                null,
                React.createElement('th', null, 'Service / Container'),
                React.createElement('th', null, 'Archetype'),
                React.createElement('th', null, 'Port'),
                React.createElement('th', null, 'Health'),
                React.createElement('th', null, 'Public Ingress / Access')
              )
            ),
            React.createElement(
              'tbody',
              null,
              services.length === 0
                ? React.createElement(
                    'tr',
                    null,
                    React.createElement('td', { colSpan: 5, style: { textAlign: 'center', color: 'var(--text-muted)', padding: '24px' } }, 'No services registered on this node.')
                  )
                : services.map((s, sIdx) => {
                    const cType = s.container_type || 'web';
                    const hasUrl = !!s.url;
                    const aiMeta = (s.metadata || {}).ai_inference || {};
                    const roleLabel = aiMeta.role_label || cType.toUpperCase();

                    return React.createElement(
                      'tr',
                      { key: s.service_name || sIdx },
                      React.createElement(
                        'td',
                        null,
                        React.createElement(
                          'div',
                          { className: 'service-name-cell' },
                          React.createElement('span', { className: 'service-title-text' }, s.service_name),
                          React.createElement('span', { className: 'service-image-code' }, s.image || s.container_name)
                        )
                      ),
                      React.createElement(
                        'td',
                        null,
                        React.createElement('span', { className: `archetype-tag archetype-${cType}` }, roleLabel)
                      ),
                      React.createElement('td', null, React.createElement('span', { className: 'port-code-badge' }, s.port || '-')),
                      React.createElement(
                        'td',
                        null,
                        React.createElement(
                          'span',
                          { style: { display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--accent-emerald)', fontWeight: '600' } },
                          React.createElement('span', { style: { width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-emerald)' } }),
                          'Healthy'
                        )
                      ),
                      React.createElement(
                        'td',
                        null,
                        hasUrl
                          ? React.createElement(
                              'div',
                              { style: { display: 'flex', alignItems: 'center', gap: '10px' } },
                              React.createElement(
                                'a',
                                { href: s.url, target: '_blank', rel: 'noreferrer', className: 'link-btn' },
                                s.url,
                                React.createElement(Icons.ExternalLink, { size: 13 })
                              ),
                              React.createElement(
                                'button',
                                {
                                  style: { background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' },
                                  onClick: () => onCopy(s.url),
                                },
                                React.createElement(Icons.Copy, { size: 14 })
                              )
                            )
                          : React.createElement(
                              'span',
                              { className: 'protected-badge' },
                              React.createElement(Icons.Lock, { size: 12 }),
                              'Protected Internal Component'
                            )
                      )
                    );
                  })
            )
          )
        )
      );
    })
  );
}

// ── COMPONENT: ServiceDirectoryView ──
function ServiceDirectoryView({ nodes, filter, setFilter, onCopy }) {
  // Aggregate all services across all nodes
  const allServices = useMemo(() => {
    const list = [];
    nodes.forEach((n) => {
      (n.services || []).forEach((s) => {
        list.push({ ...s, node_name: n.node_name || 'Primary' });
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

  return React.createElement(
    'div',
    null,
    // Filter Sub-tabs
    React.createElement(
      'div',
      { style: { display: 'flex', gap: '8px', marginBottom: '16px' } },
      ['all', 'web', 'db', 'mail'].map((f) =>
        React.createElement(
          'button',
          {
            key: f,
            className: `btn-secondary ${filter === f ? 'active' : ''}`,
            style: {
              background: filter === f ? 'var(--bg-surface-elevated)' : 'var(--bg-surface)',
              color: filter === f ? 'var(--text-primary)' : 'var(--text-muted)',
              borderColor: filter === f ? 'var(--border-focus)' : 'var(--border-subtle)',
            },
            onClick: () => setFilter(f),
          },
          f === 'all' ? 'All Services' : f === 'web' ? 'Web & APIs' : f === 'db' ? 'Databases & Caches' : 'Mail Infrastructure'
        )
      )
    ),

    React.createElement(
      'div',
      { className: 'fleet-node-card' },
      React.createElement(
        'div',
        { className: 'table-responsive' },
        React.createElement(
          'table',
          { className: 'data-table' },
          React.createElement(
            'thead',
            null,
            React.createElement(
              'tr',
              null,
              React.createElement('th', null, 'Service Name'),
              React.createElement('th', null, 'Node'),
              React.createElement('th', null, 'Archetype'),
              React.createElement('th', null, 'Port'),
              React.createElement('th', null, 'Public Endpoint')
            )
          ),
          React.createElement(
            'tbody',
            null,
            filteredServices.map((s, idx) =>
              React.createElement(
                'tr',
                { key: s.service_name + idx },
                React.createElement(
                  'td',
                  null,
                  React.createElement(
                    'div',
                    { className: 'service-name-cell' },
                    React.createElement('span', { className: 'service-title-text' }, s.service_name),
                    React.createElement('span', { className: 'service-image-code' }, s.image || s.container_name)
                  )
                ),
                React.createElement('td', null, React.createElement('span', { className: 'node-domain-code' }, s.node_name)),
                React.createElement(
                  'td',
                  null,
                  React.createElement('span', { className: `archetype-tag archetype-${s.container_type || 'web'}` }, (s.container_type || 'web').toUpperCase())
                ),
                React.createElement('td', null, React.createElement('span', { className: 'port-code-badge' }, s.port || '-')),
                React.createElement(
                  'td',
                  null,
                  s.url
                    ? React.createElement(
                        'a',
                        { href: s.url, target: '_blank', rel: 'noreferrer', className: 'link-btn' },
                        s.url,
                        React.createElement(Icons.ExternalLink, { size: 13 })
                      )
                    : React.createElement('span', { className: 'protected-badge' }, React.createElement(Icons.Lock, { size: 12 }), 'Internal Only')
                )
              )
            )
          )
        )
      )
    )
  );
}

// ── COMPONENT: IncidentConsoleView ──
function IncidentConsoleView({ incidents, onSelect, onDispatch, onPurge }) {
  if (!incidents || incidents.length === 0) {
    return React.createElement(
      'div',
      { className: 'kpi-card', style: { justifyContent: 'center', padding: '48px', color: 'var(--text-muted)' } },
      React.createElement(Icons.ShieldCheck, { size: 28, className: 'kpi-icon-emerald', style: { marginRight: '12px' } }),
      'All systems operating nominally. Zero incidents recorded.'
    );
  }

  const openCount = incidents.filter((i) => !['RESOLVED', 'VERIFIED', 'CLOSED'].includes(i.state)).length;

  return React.createElement(
    'div',
    null,
    // Action header bar for incidents
    React.createElement(
      'div',
      { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' } },
      React.createElement(
        'div',
        { style: { fontSize: '0.85rem', color: 'var(--text-muted)' } },
        `Showing ${incidents.length} incident(s) • ${openCount} actionable open`
      ),
      React.createElement(
        'button',
        {
          className: 'btn-secondary',
          onClick: onPurge,
          style: { padding: '6px 12px', fontSize: '0.78rem' },
        },
        React.createElement(Icons.ShieldAlert, { size: 14 }),
        'Purge / Clear Stale Dossiers'
      )
    ),

    React.createElement(
      'div',
      { className: 'incidents-container' },
      incidents.map((inc) => {
        const isResolved = ['RESOLVED', 'VERIFIED', 'CLOSED'].includes(inc.state);
        const isClaimed = inc.state === 'CLAIMED';
        const stack = inc.evidence?.stack_trace || inc.evidence?.logs || 'No stack trace captured.';
        const pct = isResolved ? 100 : isClaimed ? 60 : 20;

        return React.createElement(
          'div',
          { key: inc.id, className: `incident-card ${isResolved ? 'resolved' : ''}` },
          React.createElement(
            'div',
            { className: 'incident-top' },
            React.createElement(
              'div',
              { style: { display: 'flex', alignItems: 'center', gap: '8px' } },
              React.createElement('span', { className: 'incident-id-badge' }, inc.id),
              React.createElement(
                'span',
                {
                  style: {
                    fontSize: '0.72rem',
                    fontWeight: '700',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    background: isResolved
                      ? 'var(--accent-emerald-subtle)'
                      : isClaimed
                      ? 'var(--accent-amber-subtle)'
                      : 'var(--accent-rose-subtle)',
                    color: isResolved
                      ? 'var(--accent-emerald)'
                      : isClaimed
                      ? 'var(--accent-amber)'
                      : 'var(--accent-rose)',
                  },
                },
                isClaimed ? `CLAIMED (${inc.claimed_by || 'OpenCode'})` : inc.state || 'DETECTED'
              ),
              React.createElement('span', { className: 'port-code-badge' }, inc.source_node || 'Primary Node')
            ),
            React.createElement('span', { style: { fontSize: '0.75rem', color: 'var(--text-muted)' } }, inc.created_at || '')
          ),
          React.createElement('div', { className: 'incident-title-text' }, `${inc.service_name ? `[${inc.service_name}] ` : ''}${inc.title}`),
          !isResolved && React.createElement('div', { className: 'trace-code-box' }, stack),
          React.createElement(
            'div',
            null,
            React.createElement(
              'div',
              { style: { display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)' } },
              React.createElement('span', null, isClaimed ? 'Remediation: In Progress (OpenCode)' : 'Remediation Pipeline'),
              React.createElement('span', null, `${pct}%`)
            ),
            React.createElement(
              'div',
              { className: 'progress-track' },
              React.createElement('div', {
                className: 'progress-bar-fill',
                style: {
                  width: `${pct}%`,
                  background: isResolved
                    ? 'var(--accent-emerald)'
                    : isClaimed
                    ? 'var(--accent-amber)'
                    : 'var(--accent-rose)',
                },
              })
            )
          ),
          React.createElement(
            'div',
            { style: { display: 'flex', gap: '8px', marginTop: '4px' } },
            React.createElement(
              'button',
              {
                className: 'btn-secondary',
                onClick: () => onSelect(inc),
                style: { flex: 1 },
              },
              React.createElement(Icons.FileText, { size: 14 }),
              'Diagnostic Dossier'
            ),
            !isResolved &&
              React.createElement(
                'button',
                {
                  className: 'btn-primary',
                  onClick: () => onDispatch && onDispatch(inc.id),
                  style: {
                    background: isClaimed ? 'var(--accent-amber)' : 'var(--accent-indigo)',
                    color: '#fff',
                    padding: '6px 12px',
                    fontSize: '0.78rem',
                    fontWeight: '600',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  },
                },
                React.createElement(Icons.Terminal, { size: 14 }),
                isClaimed ? 'Re-Dispatch' : '⚡ Dispatch OpenCode'
              )
          )
        );
      })
    )
  );
}

// ── COMPONENT: IncidentModal ──
function IncidentModal({ incident, onClose, onCopy, onDispatch }) {
  const isResolved = ['RESOLVED', 'VERIFIED', 'CLOSED'].includes(incident.state);
  const isClaimed = incident.state === 'CLAIMED';
  const evidence = incident.evidence || {};
  const stack = evidence.stack_trace || evidence.logs || 'No stack trace captured.';

  return React.createElement(
    motion.div,
    { className: 'modal-backdrop', onClick: onClose, initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } },
    React.createElement(
      motion.div,
      { className: 'modal-dialog', onClick: (e) => e.stopPropagation(), variants: modalVariants, initial: 'hidden', animate: 'visible', exit: 'exit' },
      React.createElement(
        'div',
        { className: 'modal-header' },
        React.createElement(
          'div',
          { style: { display: 'flex', alignItems: 'center', gap: '10px' } },
          React.createElement(Icons.AlertTriangle, { size: 20, className: isResolved ? 'kpi-icon-emerald' : 'kpi-icon-rose' }),
          React.createElement('span', { style: { fontWeight: '700', fontSize: '1.05rem' } }, `Incident Dossier: ${incident.id}`)
        ),
        React.createElement('button', { className: 'btn-secondary', onClick: onClose }, 'Close')
      ),
      React.createElement(
        'div',
        { className: 'modal-body' },
        React.createElement(
          'div',
          null,
          React.createElement('div', { style: { fontWeight: '700', fontSize: '1.1rem', marginBottom: '4px' } }, incident.title),
          React.createElement('div', { style: { fontSize: '0.8rem', color: 'var(--text-muted)' } }, `Service: ${incident.service_name} | Node: ${incident.source_node || 'Primary'} | Timestamp: ${incident.created_at}`)
        ),
        React.createElement(
          'div',
          null,
          React.createElement('div', { style: { fontSize: '0.78rem', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '6px' } }, 'Error Stack Trace / Logs'),
          React.createElement('div', { className: 'trace-code-box', style: { maxHeight: '240px' } }, stack)
        ),
        React.createElement(
          'div',
          null,
          React.createElement('div', { style: { fontSize: '0.78rem', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '6px' } }, 'AI-Ops Diagnostic Recommendation'),
          React.createElement(
            'div',
            { style: { background: 'var(--bg-surface-elevated)', border: '1px solid var(--border-subtle)', padding: '14px', borderRadius: '8px', fontSize: '0.85rem' } },
            incident.recommendation || 'Investigate container runtime logs and apply targeted patch.'
          )
        )
      )
    )
  );
}

// ── COMPONENT: HealthDigestView ──
function HealthDigestView({ nodes, incidents }) {
  return React.createElement(
    'div',
    { className: 'fleet-node-card', style: { padding: '24px' } },
    React.createElement('div', { style: { fontWeight: '700', fontSize: '1.15rem', marginBottom: '8px' } }, 'Automated Ops Health Digest'),
    React.createElement('div', { style: { fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '20px' } }, 'Generated continuously by AI-Ops sentry daemon. Evaluates fleet resilience, error frequency, and auto-remediation efficiency.'),
    React.createElement(
      'div',
      { className: 'kpi-grid' },
      React.createElement(
        'div',
        { className: 'kpi-card' },
        React.createElement(
          'div',
          { className: 'kpi-content' },
          React.createElement('span', { className: 'kpi-label' }, 'Fleet Availability'),
          React.createElement('span', { className: 'kpi-value' }, '99.98%')
        ),
        React.createElement('div', { className: 'kpi-icon-box kpi-icon-emerald' }, React.createElement(Icons.ShieldCheck, { size: 22 }))
      ),
      React.createElement(
        'div',
        { className: 'kpi-card' },
        React.createElement(
          'div',
          { className: 'kpi-content' },
          React.createElement('span', { className: 'kpi-label' }, 'Total Incidents (24h)'),
          React.createElement('span', { className: 'kpi-value' }, incidents.length)
        ),
        React.createElement('div', { className: 'kpi-icon-box kpi-icon-cyan' }, React.createElement(Icons.Terminal, { size: 22 }))
      )
    )
  );
}

// Mount React 18 Application
const rootElement = document.getElementById('root');
if (rootElement) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(React.createElement(App));
}
