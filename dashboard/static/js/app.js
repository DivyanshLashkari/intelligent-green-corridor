/**
 * Green Corridor Control Room -- WebSocket Telemetry & Chart.js Logic
 *
 * Connects to ws://localhost:8000/ws/telemetry and dynamically updates
 * all five dashboard panels on each incoming JSON payload.
 */

// ── State ──────────────────────────────────────────────────────────────

const MAX_CHART_POINTS = 20;
const V_THRESH = 15.0;

let varianceData = [];
let timeLabels = [];
let varianceChart = null;
let wsConnected = false;
let ws = null;
let reconnectTimer = null;

// ── WebSocket Connection ───────────────────────────────────────────────

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        wsConnected = true;
        updateConnectionStatus(true);
        console.log('[WS] Connected to telemetry stream');
        if (reconnectTimer) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
        }
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateDashboard(data);
        } catch (e) {
            console.warn('[WS] Parse error:', e);
        }
    };

    ws.onclose = () => {
        wsConnected = false;
        updateConnectionStatus(false);
        console.log('[WS] Disconnected -- reconnecting in 3s...');
        if (!reconnectTimer) {
            reconnectTimer = setInterval(() => {
                if (!wsConnected) connectWebSocket();
            }, 3000);
        }
    };

    ws.onerror = (err) => {
        console.error('[WS] Error:', err);
        ws.close();
    };
}

// ── Dashboard Update Dispatcher ────────────────────────────────────────

function updateDashboard(data) {
    updateSimTime(data);
    updateVisionPanel(data);
    updateRoutingPanel(data);
    updateArbitrationPanel(data);
    updateVMSPanel(data);
    updateMetricsPanel(data);
    updateMapPanel(data);
}

// ── Panel 1: AI Perception Feed ────────────────────────────────────────

function updateVisionPanel(data) {
    const statusEl = document.getElementById('vision-status');
    const varianceEl = document.getElementById('vision-variance');
    const confidenceEl = document.getElementById('vision-confidence');

    // Determine status from primary ambulance or first available
    const ambs = data.ambulances || {};
    const primaryAmb = ambs['amb_0'] || Object.values(ambs)[0] || {};
    const status = primaryAmb.vision_status || 'UNKNOWN';
    const variance = primaryAmb.temporal_variance ?? 0;
    const confidence = primaryAmb.confidence ?? 0;

    // Status badge
    if (status === 'ACTIVE_EMERGENCY') {
        statusEl.innerHTML = `<span class="badge badge-active">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
            ACTIVE EMERGENCY (Siren Verified)</span>`;
    } else {
        statusEl.innerHTML = `<span class="badge badge-offduty">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            OFF-DUTY (No Flashing)</span>`;
    }

    // Numeric readouts
    varianceEl.textContent = variance.toFixed(1);
    varianceEl.className = `metric-value ${variance >= V_THRESH ? 'green' : 'red'}`;
    confidenceEl.textContent = (confidence * 100).toFixed(0) + '%';

    // Update chart
    updateVarianceChart(data.sim_time ?? varianceData.length, variance);
}

function updateVarianceChart(time, variance) {
    timeLabels.push(time.toFixed(0) + 's');
    varianceData.push(variance);

    if (timeLabels.length > MAX_CHART_POINTS) {
        timeLabels.shift();
        varianceData.shift();
    }

    if (varianceChart) {
        varianceChart.data.labels = timeLabels;
        varianceChart.data.datasets[0].data = varianceData;
        varianceChart.update('none');
    }
}

// ── Panel 2: Network & Routing ─────────────────────────────────────────

function updateRoutingPanel(data) {
    const routeEl = document.getElementById('route-edges');
    const phaseEl = document.getElementById('route-phase');

    const ambs = data.ambulances || {};
    const primary = ambs['amb_0'] || Object.values(ambs)[0] || {};
    const route = primary.route || [];
    const edgeIdx = primary.edge_idx ?? 0;

    // Build route edge chips
    let html = '';
    const displayEdges = route.slice(0, 8);
    displayEdges.forEach((edge, i) => {
        const isCurrent = i === edgeIdx;
        html += `<span class="route-edge ${isCurrent ? 'current' : ''}">${edge}</span>`;
        if (i < displayEdges.length - 1) {
            html += `<span class="route-arrow">&rarr;</span>`;
        }
    });
    if (route.length > 8) {
        html += `<span class="route-arrow">... +${route.length - 8}</span>`;
    }
    routeEl.innerHTML = html || '<span style="color:#6b7280">No route computed</span>';

    // Phase indicator
    const phase = primary.phase || 'STATIC';
    if (phase === 'GREEN_WAVE') {
        phaseEl.innerHTML = `<div class="phase-indicator phase-green">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10"/></svg>
            GREEN WAVE -- PRIORITY PREEMPTION ACTIVE
        </div>`;
    } else {
        phaseEl.innerHTML = `<div class="phase-indicator phase-static">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
                <line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/>
            </svg>
            STANDARD CYCLIC -- NO PREEMPTION
        </div>`;
    }
}

// ── Panel 3: Conflict Arbitration Queue ────────────────────────────────

function updateArbitrationPanel(data) {
    const tbody = document.getElementById('arb-tbody');
    const evs = data.approaching_evs || [];
    const deadlocks = data.arbitration?.deadlocks ?? 0;
    const resolved = data.arbitration?.conflicts_resolved ?? 0;

    document.getElementById('arb-deadlocks').textContent = deadlocks;
    document.getElementById('arb-resolved').textContent = resolved;

    if (evs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:16px">
            No vehicles within detection radius</td></tr>`;
        return;
    }

    // Sort by ETA
    evs.sort((a, b) => a.eta - b.eta);

    let html = '';
    evs.forEach((ev, i) => {
        const rowClass = i === 0 ? 'priority-1' : 'queued';
        const priorityBadge = i === 0
            ? '<span class="badge badge-active">P1 - PROCEED</span>'
            : `<span class="badge badge-queued">P${i + 1} - YIELD</span>`;

        html += `<tr class="${rowClass}">
            <td>${ev.vehicle_id}</td>
            <td>${ev.distance.toFixed(1)}</td>
            <td>${ev.speed.toFixed(1)}</td>
            <td>${ev.eta.toFixed(1)}</td>
            <td>${priorityBadge}</td>
        </tr>`;
    });
    tbody.innerHTML = html;
}

// ── Panel 4: VMS Display ───────────────────────────────────────────────

function updateVMSPanel(data) {
    const vmsEl = document.getElementById('vms-message');
    const vmsMsg = data.vms_message || '';

    if (vmsMsg) {
        vmsEl.textContent = vmsMsg;
        vmsEl.style.opacity = '1';
    } else {
        vmsEl.textContent = 'SYSTEM STANDBY -- NO ACTIVE CORRIDOR PREEMPTION';
        vmsEl.style.opacity = '0.5';
    }
}

// ── Panel 5: Performance Metrics ───────────────────────────────────────

function updateMetricsPanel(data) {
    const metrics = data.metrics || {};

    const proposedTT = metrics.proposed_travel_time ?? 0;
    const baselineTT = metrics.baseline_travel_time ?? 0;
    const reduction = baselineTT > 0 ? ((baselineTT - proposedTT) / baselineTT * 100) : 0;
    const waitTime = metrics.signal_wait ?? 0;

    document.getElementById('metric-proposed-tt').textContent = proposedTT.toFixed(1) + 's';
    document.getElementById('metric-baseline-tt').textContent = baselineTT.toFixed(1) + 's';

    const reductionEl = document.getElementById('metric-reduction');
    reductionEl.textContent = reduction.toFixed(1) + '%';
    reductionEl.className = `metric-value ${reduction >= 30 ? 'green' : 'amber'}`;

    const waitEl = document.getElementById('metric-wait');
    waitEl.textContent = waitTime.toFixed(1) + 's';
    waitEl.className = `metric-value ${waitTime <= 5 ? 'green' : 'red'}`;
}

// ── Sim Time & Progress ────────────────────────────────────────────────

function updateSimTime(data) {
    const simTime = data.sim_time ?? 0;
    const simDuration = data.sim_duration ?? 300;
    const step = data.step ?? 0;
    const mode = data.mode ?? 'proposed';

    document.getElementById('sim-time').textContent = `T=${simTime.toFixed(0)}s`;
    document.getElementById('sim-step').textContent = `Step ${step}`;
    document.getElementById('sim-mode').textContent = mode.toUpperCase();

    const pct = Math.min(100, (simTime / simDuration) * 100);
    document.getElementById('sim-progress-bar').style.width = pct + '%';

    // Check if simulation is complete
    if (simTime >= simDuration) {
        document.getElementById('sim-status-text').textContent = 'COMPLETE';
        document.getElementById('sim-status-dot').className = 'status-dot offline';
    }
}

// ── Map Canvas Drawing ──────────────────────────────────────────────────

function updateMapPanel(data) {
    const canvas = document.getElementById('sim-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    // Clear background
    ctx.clearRect(0, 0, w, h);

    // Grid config (4x4, 200m spacing -> 600m total size)
    const scale = 0.55;
    const offsetX = (w - (600 * scale)) / 2;
    const offsetY = (h - (600 * scale)) / 2;

    function getX(sumoX) { return offsetX + sumoX * scale; }
    function getY(sumoY) { return h - (offsetY + sumoY * scale); }

    // 1. Draw base grid network
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    for (let r = 0; r < 4; r++) {
        for (let c = 0; c < 4; c++) {
            const x = c * 200;
            const y = r * 200;
            if (c < 3) {
                ctx.beginPath(); ctx.moveTo(getX(x), getY(y)); ctx.lineTo(getX(x+200), getY(y)); ctx.stroke();
            }
            if (r < 3) {
                ctx.beginPath(); ctx.moveTo(getX(x), getY(y)); ctx.lineTo(getX(x), getY(y+200)); ctx.stroke();
            }
            // Draw intersection nodes
            ctx.beginPath(); ctx.arc(getX(x), getY(y), 4, 0, Math.PI*2); 
            ctx.fillStyle = '#374151'; ctx.fill();
        }
    }

    // 2. Highlight blocked edges
    if (data.blocked_edges && data.blocked_edges.length > 0) {
        ctx.strokeStyle = '#ef4444'; // Red
        ctx.lineWidth = 5;
        data.blocked_edges.forEach(eid => {
            const parts = eid.split('_');
            if (parts.length === 6) {
                const fr = parseInt(parts[1]); const fc = parseInt(parts[2]);
                const tr = parseInt(parts[4]); const tc = parseInt(parts[5]);
                ctx.beginPath();
                ctx.moveTo(getX(fc*200), getY(fr*200));
                ctx.lineTo(getX(tc*200), getY(tr*200));
                ctx.stroke();
                
                // Draw 'X' block symbol in middle
                const mx = getX((fc+tc)*100); const my = getY((fr+tr)*100);
                ctx.fillStyle = '#ef4444'; ctx.font = '14px sans-serif'; ctx.textAlign = 'center';
                ctx.fillText('✖', mx, my + 5);
            }
        });
    }

    // 3. Draw Ambulances
    const ambs = data.ambulances || {};
    Object.keys(ambs).forEach(aid => {
        const amb = ambs[aid];
        if (!amb.position) return;
        const [x, y] = amb.position;
        
        const cx = getX(x);
        const cy = getY(y);
        const isEmergency = amb.vision_status === 'ACTIVE_EMERGENCY';

        // Animated pulse halo
        const pulse = (Date.now() % 1000) / 1000;
        const isRedPhase = (Date.now() % 500) < 250;
        let haloColor, coreColor;
        if (isEmergency) {
            haloColor = isRedPhase ? `rgba(239, 68, 68, ${1-pulse})` : `rgba(6, 182, 212, ${1-pulse})`;
            coreColor = isRedPhase ? '#ef4444' : '#06b6d4';
        } else {
            haloColor = `rgba(156, 163, 175, ${0.5 - pulse*0.5})`;
            coreColor = '#9ca3af';
        }

        ctx.beginPath();
        ctx.arc(cx, cy, 10 + (pulse * 10), 0, Math.PI*2);
        ctx.fillStyle = haloColor;
        ctx.fill();

        // Core dot
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, Math.PI*2);
        ctx.fillStyle = coreColor;
        ctx.shadowColor = isEmergency ? coreColor : 'transparent';
        ctx.shadowBlur = isEmergency ? 10 : 0;
        ctx.fill();
        ctx.shadowBlur = 0; // reset
        
        // Label
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 11px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(aid, cx + 12, cy - 8);

        // Destination Marker
        if (amb.target_position) {
            const [tx, ty] = amb.target_position;
            const tcx = getX(tx);
            const tcy = getY(ty);
            
            ctx.beginPath();
            ctx.setLineDash([5, 5]);
            ctx.moveTo(cx, cy);
            ctx.lineTo(tcx, tcy);
            ctx.strokeStyle = `rgba(255, 255, 255, 0.3)`;
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.setLineDash([]);
            
            ctx.beginPath();
            ctx.arc(tcx, tcy, 4, 0, Math.PI*2);
            ctx.fillStyle = '#10b981';
            ctx.fill();
            ctx.fillText('DEST ' + aid, tcx + 8, tcy + 4);
        }
    });
}

// ── Connection Status ──────────────────────────────────────────────────

function updateConnectionStatus(connected) {
    const dot = document.getElementById('ws-status-dot');
    const text = document.getElementById('ws-status-text');
    if (connected) {
        dot.className = 'status-dot online';
        text.textContent = 'LIVE';
    } else {
        dot.className = 'status-dot offline';
        text.textContent = 'OFFLINE';
    }
}

// ── Chart.js Initialization ────────────────────────────────────────────

function initChart() {
    const ctx = document.getElementById('variance-chart');
    if (!ctx) return;

    varianceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: timeLabels,
            datasets: [
                {
                    label: 'Red/Blue Pixel Variance',
                    data: varianceData,
                    borderColor: '#06b6d4',
                    backgroundColor: 'rgba(6, 182, 212, 0.08)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 2,
                    pointBackgroundColor: '#06b6d4',
                },
                {
                    label: 'V_thresh = 15.0',
                    data: new Array(MAX_CHART_POINTS).fill(V_THRESH),
                    borderColor: '#ef4444',
                    borderWidth: 1.5,
                    borderDash: [6, 3],
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#6b7280', font: { size: 9 }, maxTicksLimit: 8 },
                },
                y: {
                    display: true,
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#6b7280', font: { size: 9 } },
                    suggestedMin: 0,
                    suggestedMax: 50,
                },
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#9ca3af',
                        font: { size: 10, family: "'JetBrains Mono', monospace" },
                        boxWidth: 14,
                        padding: 10,
                    },
                },
            },
        },
    });
}

// ── Boot ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initChart();
    connectWebSocket();

    const selector = document.getElementById('scenario-selector');
    if (selector) {
        selector.addEventListener('change', async (e) => {
            const val = e.target.value;
            try {
                await fetch('/api/set_scenario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scenario: val })
                });
                console.log(`Scenario changed to ${val}`);
                // Clear chart data on reset
                timeLabels = [];
                varianceData = [];
                if (varianceChart) varianceChart.update('none');
            } catch (err) {
                console.error('Failed to change scenario:', err);
            }
        });
    }
});

