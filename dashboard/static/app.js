/**
 * AI-Ops & Dev Status Dashboard Frontend Client
 */

let activeTab = 'services';

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
      document.getElementById(`tab-${activeTab}`).classList.add('active');
    });
  });
}

function setupRefresh() {
  document.getElementById('refresh-btn').addEventListener('click', () => {
    fetchData();
    showToast('Refreshed status data.');
  });
}

async function fetchData() {
  try {
    const [statusRes, incidentsRes, screenshotsRes] = await Promise.all([
      fetch('/api/status').then((r) => r.json()),
      fetch('/api/incidents').then((r) => r.json()),
      fetch('/api/screenshots').then((r) => r.json()),
    ]);

    renderOverview(statusRes, incidentsRes);
    renderServices(statusRes.services || []);
    renderIncidents(incidentsRes.incidents || []);
    renderScreenshots(screenshotsRes.screenshots || []);
  } catch (err) {
    console.error('Failed to fetch status data:', err);
  }
}

function renderOverview(status, incidentsData) {
  if (status.base_domain) {
    document.getElementById('wildcard-scope').textContent = `*.${status.base_domain}`;
  }
  if (status.network) {
    document.getElementById('network-badge').textContent = status.network;
  }

  document.getElementById('count-services').textContent = status.services?.length || 0;
  document.getElementById('count-containers').textContent = status.total_containers || 0;

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

function renderServices(services) {
  const container = document.getElementById('service-list');
  if (!services || services.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        No active services exposed yet.<br>
        Run <code>devctl expose &lt;service&gt; &lt;port&gt;</code> to register one.
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
          </div>
          <div class="health-status-badge ${statusClass}">
            ${statusText}
          </div>
        </div>

        <div class="card-url-row">
          <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" class="service-url">
            ${escapeHtml(s.url)}
          </a>
          <button class="copy-btn" onclick="copyToClipboard('${escapeHtml(s.url)}')">Copy</button>
        </div>

        <div class="card-meta-row">
          <span>Container: <strong>${escapeHtml(s.container_name || s.service_name)}:${s.port || ''}</strong></span>
          <span>Restarts: <strong>${s.restart_count ?? 0}</strong></span>
        </div>
      </div>`;
    })
    .join('');
}

function renderIncidents(incidents) {
  const container = document.getElementById('incident-list');
  if (!incidents || incidents.length === 0) {
    container.innerHTML = `<div class="empty-state">✅ No active incidents. All services are healthy.</div>`;
    return;
  }

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
              <strong>Live Test URL:</strong> <a href="${escapeHtml(proof.live_url || inc.evidence?.failing_url || '#')}" target="_blank" style="color: var(--accent-cyan);">${escapeHtml(proof.live_url || inc.evidence?.failing_url || '')}</a>
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
      </div>`;
    })
    .join('');
}

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
