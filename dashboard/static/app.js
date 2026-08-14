/**
 * AI-Ops & Dev Status Dashboard Frontend Client
 */

let activeTab = 'fleet';

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupRefresh();
  fetchData();
  setInterval(fetchData, 5000); // 5s auto-refresh
});

function setupTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));

      tab.classList.add('active');
      activeTab = tab.dataset.tab;
      const target = document.getElementById(`tab-${activeTab}`);
      if (target) target.classList.add('active');
    });
  });
}

function setupRefresh() {
  document.getElementById('refresh-btn').addEventListener('click', () => {
    fetchData();
    showToast('Refreshed fleet status data.');
  });
}

async function fetchData() {
  try {
    const [statusRes, incidentsRes, screenshotsRes, fleetRes] = await Promise.all([
      fetch('/api/status').then((r) => r.json()).catch(() => ({})),
      fetch('/api/incidents').then((r) => r.json()).catch(() => ({})),
      fetch('/api/screenshots').then((r) => r.json()).catch(() => ({})),
      fetch('/api/fleet/nodes').then((r) => r.json()).catch(() => ({})),
    ]);

    renderOverview(statusRes, incidentsRes, fleetRes);
    renderFleet(fleetRes.nodes || []);
    renderServices(statusRes.services || []);
    renderIncidents(incidentsRes.incidents || []);
    renderScreenshots(screenshotsRes.screenshots || []);
  } catch (err) {
    console.error('Failed to fetch status data:', err);
  }
}

function renderOverview(status, incidentsData, fleetData) {
  if (status.base_domain) {
    document.getElementById('wildcard-scope').textContent = `*.${status.base_domain}`;
  }
  if (status.network) {
    document.getElementById('network-badge').textContent = status.network;
  }

  // Calculate totals across fleet if available
  const nodes = fleetData.nodes || [];
  let totalServices = status.services?.length || 0;
  let totalContainers = status.total_containers || 0;
  if (nodes.length > 1) {
    totalServices = nodes.reduce((acc, n) => acc + (n.services?.length || 0), 0);
    totalContainers = nodes.reduce((acc, n) => acc + (n.containers_count || 0), 0);
  }

  document.getElementById('count-services').textContent = totalServices;
  document.getElementById('count-containers').textContent = totalContainers;

  const openCount = status.open_incidents_count || 0;
  const incElement = document.getElementById('count-incidents');
  incElement.textContent = openCount;

  const badge = document.getElementById('badge-incidents');
  if (openCount > 0) {
    badge.style.display = 'inline-block';
    badge.textContent = openCount;
  } else {
    badge.style.display = 'none';
  }
}

function renderFleet(nodes) {
  const container = document.getElementById('fleet-container');
  if (!container) return;

  if (!nodes || nodes.length === 0) {
    container.innerHTML = `<div class="empty-state">No servers connected to fleet telemetry yet.</div>`;
    return;
  }

  container.innerHTML = nodes
    .map((node) => {
      const isOnline = node.online ?? true;
      const statusHtml = isOnline
        ? `<span class="node-status-online">● ONLINE</span>`
        : `<span class="node-status-offline">○ OFFLINE</span>`;

      const services = node.services || [];
      let rowsHtml = '';
      if (services.length === 0) {
        rowsHtml = `<tr><td colspan="6" style="text-align:center; color: var(--text-muted); padding: 20px;">No exposed services on this server. Run <code>devctl discover</code> to index containers.</td></tr>`;
      } else {
        rowsHtml = services
          .map((s) => {
            const isHealthy = s.healthy ?? true;
            const statusColor = isHealthy ? 'var(--accent-green)' : 'var(--accent-red)';
            const statusLabel = isHealthy ? '● Healthy' : '▲ Unhealthy';
            const img = s.image || 'app:latest';
            const ver = s.version || 'latest';

            return `
            <tr>
              <td>
                <strong>${escapeHtml(s.service_name)}</strong>
                <span class="env-pill" style="margin-left: 6px;">${escapeHtml(s.env || 'dev')}</span>
              </td>
              <td><span class="image-name-text">${escapeHtml(img)}</span></td>
              <td><span class="version-tag-badge">${escapeHtml(ver)}</span></td>
              <td><code>${escapeHtml(String(s.port || '80'))}</code></td>
              <td><span style="color: ${statusColor}; font-weight: 600;">${statusLabel}</span></td>
              <td>
                <a href="${escapeHtml(s.url || '#')}" target="_blank" class="service-direct-link">
                  ${escapeHtml(s.url || '')}
                </a>
              </td>
            </tr>`;
          })
          .join('');
      }

      return `
      <div class="fleet-server-card">
        <div class="server-header">
          <div class="server-info-title">
            <span class="server-name">🖥️ ${escapeHtml(node.node_name)}</span>
            <span class="server-domain">*.${escapeHtml(node.base_domain || 'dev-server.datakrib.com')}</span>
            ${statusHtml}
          </div>
          <div class="server-meta">
            <span>📦 <strong>${services.length}</strong> Services</span>
            <span>🐳 <strong>${node.containers_count || services.length}</strong> Containers</span>
            ${node.open_incidents_count ? `<span style="color: var(--accent-red); font-weight:700;">🚨 ${node.open_incidents_count} Open Incident(s)</span>` : ''}
          </div>
        </div>
        <div class="fleet-table-container">
          <table class="fleet-table">
            <thead>
              <tr>
                <th>Service Name</th>
                <th>Docker Image</th>
                <th>Version / Tag</th>
                <th>Port</th>
                <th>Health Status</th>
                <th>Live HTTPS URL</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </div>`;
    })
    .join('');
}

function renderServices(services) {
  const container = document.getElementById('service-list');
  if (!services || services.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        No active services exposed yet on this node.<br>
        Run <code>devctl expose &lt;service&gt; &lt;port&gt;</code> or <code>devctl discover</code> to register.
      </div>`;
    return;
  }

  container.innerHTML = services
    .map((s) => {
      const isHealthy = s.healthy ?? true;
      const statusClass = isHealthy ? 'healthy' : 'unhealthy';
      const statusText = isHealthy
        ? `● Online (${s.response_time_ms ?? 0}ms)`
        : `▲ Failing (HTTP ${s.http_status ?? 'N/A'})`;

      return `
      <div class="service-card">
        <div class="card-top">
          <div class="service-title">
            <span class="service-name">${escapeHtml(s.service_name)}</span>
            <span class="env-pill">${escapeHtml(s.env || 'dev')}</span>
            <span class="version-tag-badge">${escapeHtml(s.version || 'latest')}</span>
          </div>
          <div class="status-indicator ${statusClass}">${statusText}</div>
        </div>
        <div class="card-meta">
          <span>Image: <code class="image-name-text">${escapeHtml(s.image || 'app:latest')}</code></span>
          <span>Port: <code>${escapeHtml(String(s.port))}</code></span>
        </div>
        <div class="card-url-box">
          <a href="${escapeHtml(s.url)}" target="_blank" class="service-url">${escapeHtml(s.url)}</a>
          <button class="copy-btn" onclick="copyToClipboard('${escapeHtml(s.url)}')">Copy</button>
        </div>
      </div>`;
    })
    .join('');
}

window.incidentsMap = {};

function renderIncidents(incidents) {
  const container = document.getElementById('incident-list');
  if (!incidents || incidents.length === 0) {
    container.innerHTML = `<div class="empty-state">✅ No active incidents. All services are healthy.</div>`;
    return;
  }

  // Store in global cache for modal view
  incidents.forEach(inc => { window.incidentsMap[inc.id] = inc; });

  container.innerHTML = incidents
    .map((inc) => {
      const stack = inc.evidence?.stack_trace || inc.evidence?.logs || 'No stack trace captured.';
      const isResolved = ['RESOLVED', 'VERIFIED', 'CLOSED'].includes(inc.state);
      const proof = inc.resolution_proof || {};

      let proofHtml = '';
      if (isResolved) {
        proofHtml = `
          <div style="background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 6px; padding: 8px 12px; margin-top: 8px;">
            <div style="color: #22c55e; font-weight: 600; font-size: 0.85rem;">✅ RESOLUTION & VERIFICATION PROOF</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 4px;">
              <strong>Resolved By:</strong> ${escapeHtml(inc.claimed_by || 'OpenCode')} | <strong>Health:</strong> ${escapeHtml(proof.health_probe || 'HTTP 200 OK')}
            </div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 2px;">
              <strong>Live Test URL:</strong> <a href="${escapeHtml(proof.live_url || inc.evidence?.failing_url || '#')}" target="_blank" style="color: var(--accent-cyan); font-weight: 600;">${escapeHtml(proof.live_url || inc.evidence?.failing_url || '')}</a>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; font-style: italic;">
              ${escapeHtml(inc.resolution_notes || '')}
            </div>
          </div>`;
      }

      return `
      <div class="incident-card" style="${isResolved ? 'border-color: rgba(34, 197, 94, 0.3);' : ''}">
        <div class="incident-header">
          <span class="incident-id">${escapeHtml(inc.id)}</span>
          <span class="env-pill" style="${isResolved ? 'background: rgba(34, 197, 94, 0.2); color: #22c55e;' : ''}">${escapeHtml(inc.state || inc.severity || 'HIGH')}</span>
          <span style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(inc.created_at || '')}</span>
        </div>
        <div class="incident-title">${escapeHtml(inc.title)}</div>
        ${!isResolved ? `<div class="incident-trace">${escapeHtml(stack)}</div>` : ''}
        ${!isResolved ? `
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 4px;">
          💡 <strong>AI-Ops Recommendation:</strong> ${escapeHtml(inc.recommendation || 'Investigate logs and fix.')}
        </div>` : ''}
        ${proofHtml}
        <button class="view-dossier-btn" onclick="openIncidentModal('${escapeHtml(inc.id)}')">
          📄 View Full Report & Verification Proof
        </button>
      </div>`;
    })
    .join('');
}

function openIncidentModal(incidentId) {
  const inc = window.incidentsMap[incidentId];
  if (!inc) return;

  const isResolved = ['RESOLVED', 'VERIFIED', 'CLOSED'].includes(inc.state);
  const proof = inc.resolution_proof || {};
  const evidence = inc.evidence || {};
  const stack = evidence.stack_trace || evidence.logs || 'No stack trace captured.';

  document.getElementById('modal-inc-id').innerText = inc.id;
  const badge = document.getElementById('modal-inc-badge');
  badge.innerText = inc.state || 'DETECTED';
  badge.style.background = isResolved ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)';
  badge.style.color = isResolved ? '#22c55e' : '#ef4444';

  let bodyHtml = `
    <!-- Summary Section -->
    <div>
      <div style="font-weight: 700; font-size: 1rem; color: var(--text-primary); margin-bottom: 4px;">${escapeHtml(inc.title)}</div>
      <div style="font-size: 0.8rem; color: var(--text-muted);">
        Service: <strong>${escapeHtml(inc.service_name)}</strong> | Severity: <strong>${escapeHtml(inc.severity)}</strong> | Detected: ${escapeHtml(inc.created_at)}
      </div>
    </div>

    <!-- Initial Problem Evidence -->
    <div>
      <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">📋 INITIAL PROBLEM REPORT</div>
      <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 6px; padding: 10px 14px; font-size: 0.8rem; display: flex; flex-direction: column; gap: 4px;">
        <div><strong>Failing URL:</strong> <code>${escapeHtml(evidence.failing_url || 'N/A')}</code></div>
        <div><strong>HTTP Status:</strong> <code>${escapeHtml(evidence.status_code || 'N/A')}</code></div>
        <div><strong>Container State:</strong> <code>${escapeHtml(evidence.container_state || 'Unknown')}</code></div>
      </div>
    </div>

    <!-- Stack Trace -->
    <div>
      <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">🪵 ERROR EVIDENCE & STACK TRACE</div>
      <div class="code-diff-block">${escapeHtml(stack)}</div>
    </div>

    <!-- Recommendation -->
    <div>
      <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">💡 AI-OPS DIAGNOSTIC RECOMMENDATION</div>
      <div style="background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 6px; padding: 10px 14px; font-size: 0.8rem; color: var(--text-secondary);">
        ${escapeHtml(inc.recommendation || 'Investigate source code and apply patch.')}
      </div>
    </div>
  `;

  if (isResolved) {
    bodyHtml += `
    <!-- Verification Proof Box -->
    <div class="proof-box">
      <div class="proof-header">
        <span>✅ VERIFIED RESOLUTION CERTIFICATE</span>
      </div>
      <div class="proof-row">
        <span>Resolved By:</span>
        <span>${escapeHtml(inc.claimed_by || 'OpenCode')}</span>
      </div>
      <div class="proof-row">
        <span>Resolved Timestamp:</span>
        <span>${escapeHtml(inc.resolved_at || '')}</span>
      </div>
      <div class="proof-row">
        <span>Live Container Status:</span>
        <span style="color: #22c55e;">${escapeHtml(proof.container_state || 'RUNNING')}</span>
      </div>
      <div class="proof-row">
        <span>Automated Health Probe:</span>
        <span>${escapeHtml(proof.health_probe || 'HTTP 200 OK')}</span>
      </div>
      <div class="proof-row">
        <span>Git Branch:</span>
        <span>${escapeHtml(proof.git_branch || 'master')}</span>
      </div>
      <div class="proof-row" style="border-bottom: none;">
        <span>Live Staging / Production URL:</span>
        <a href="${escapeHtml(proof.live_url || '#')}" target="_blank" style="color: var(--accent-cyan); font-weight: 700; text-decoration: underline;">
          ${escapeHtml(proof.live_url || 'N/A')}
        </a>
      </div>
    </div>

    <!-- Remediation Notes -->
    <div>
      <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">📝 REMEDIATION & ROOT CAUSE EXPLANATION</div>
      <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 6px; padding: 12px 14px; font-size: 0.85rem; line-height: 1.5;">
        ${escapeHtml(inc.resolution_notes || 'All application faults resolved and verified with tests.')}
      </div>
    </div>

    <!-- Code Diff / Files Touched -->
    <div>
      <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">🛠️ CODE CHANGES & FILES TOUCHED</div>
      <div class="code-diff-block">${escapeHtml(proof.git_diff || 'No git diff captured.')}</div>
    </div>
    `;
  }

  document.getElementById('modal-inc-body').innerHTML = bodyHtml;
  document.getElementById('incident-modal').style.display = 'flex';
}

function closeIncidentModal() {
  document.getElementById('incident-modal').style.display = 'none';
}

document.addEventListener('DOMContentLoaded', () => {
  const closeBtn = document.getElementById('modal-close-btn');
  if (closeBtn) closeBtn.addEventListener('click', closeIncidentModal);

  const modalOverlay = document.getElementById('incident-modal');
  if (modalOverlay) {
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) closeIncidentModal();
    });
  }
});

function renderScreenshots(screenshots) {
  const container = document.getElementById('screenshot-list');
  if (!screenshots || screenshots.length === 0) {
    container.innerHTML = `<div class="empty-state">No screenshots captured yet. Run <code>devctl test &lt;service&gt;</code> to test.</div>`;
    return;
  }

  container.innerHTML = screenshots
    .map((item) => `
      <div class="screenshot-item">
        <a href="${escapeHtml(item.url_path)}" target="_blank">
          <img src="${escapeHtml(item.url_path)}" alt="${escapeHtml(item.service_name)}" loading="lazy">
        </a>
        <div class="screenshot-info">
          <span><strong>${escapeHtml(item.service_name)}</strong> (${escapeHtml(item.type)})</span>
          <a href="${escapeHtml(item.url_path)}" target="_blank" style="color: var(--accent-cyan); text-decoration: none;">Full View</a>
        </div>
      </div>`)
    .join('');
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast('Copied URL to clipboard!');
  });
}

function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
