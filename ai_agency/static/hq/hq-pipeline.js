/**
 * HQPipeline — JS namespace for /api/pipeline/* (T-4-008, Sprint 4).
 *
 * Used by pipeline.html and pipeline-run-detail.html. All calls go through
 * hqAuthHeaders() from _components.js so X-Auth-Token is consistent.
 */
(function (global) {
  'use strict';

  const BASE = '/api/pipeline';

  function _headers() {
    // hqAuthHeaders is defined in _components.js
    return (typeof hqAuthHeaders === 'function') ? hqAuthHeaders() : {};
  }

  async function _fetchJson(url, opts) {
    const res = await fetch(url, {
      ...opts,
      headers: { 'Content-Type': 'application/json', ..._headers(), ...(opts && opts.headers) },
    });
    if (res.status === 401) {
      // Bubble up so pages can redirect to login.
      throw new Error('UNAUTHORIZED');
    }
    if (!res.ok) {
      let detail = '';
      try { detail = (await res.json()).detail || ''; } catch (_) { detail = res.statusText; }
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    return res.json();
  }

  const HQPipeline = {

    // ── CRUD ─────────────────────────────────────────────────────────

    async listRuns(filters) {
      filters = filters || {};
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      params.set('limit', filters.limit || 50);
      params.set('offset', filters.offset || 0);
      return _fetchJson(`${BASE}/runs?${params.toString()}`);
    },

    async createRun(data) {
      return _fetchJson(`${BASE}/runs`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },

    async getRun(id) {
      return _fetchJson(`${BASE}/runs/${id}`);
    },

    async getEvents(id, opts) {
      opts = opts || {};
      const params = new URLSearchParams();
      params.set('limit', opts.limit || 100);
      if (opts.since != null) params.set('since', opts.since);
      return _fetchJson(`${BASE}/runs/${id}/events?${params.toString()}`);
    },

    // ── Management actions (T-3-012 + Sprint 3 backlog v1.1) ─────────

    async approveRun(id) {
      return _fetchJson(`${BASE}/runs/${id}/approve`, { method: 'POST' });
    },

    // Pause/Resume/Abort — backend implemented (post-v1.0 polish).
    async pauseRun(id) { return _fetchJson(`${BASE}/runs/${id}/pause`, { method: 'POST' }); },
    async resumeRun(id) { return _fetchJson(`${BASE}/runs/${id}/resume`, { method: 'POST' }); },
    async abortRun(id) { return _fetchJson(`${BASE}/runs/${id}/abort`, { method: 'POST' }); },

    // ── HI-3 Sprints + HI-2 Files (v1.1) ─────────────────────────────

    async listSprints(id) {
      return _fetchJson(`${BASE}/runs/${id}/sprints`);
    },

    // v1.2: rate limits state for pipeline.html indicator
    async getRateLimits() {
      return _fetchJson(`${BASE}/rate-limits`);
    },

    async listFiles(id) {
      return _fetchJson(`${BASE}/runs/${id}/files`);
    },

    async getFileContent(id, path) {
      // path is encoded as part of the URL path (FastAPI :path converter)
      const safePath = path.split('/').map(encodeURIComponent).join('/');
      return _fetchJson(`${BASE}/runs/${id}/files/${safePath}`);
    },

    // ── WebSocket live events ────────────────────────────────────────

    /**
     * Robust WS connection with auto-reconnect (HI-5, v1.1).
     *
     * - Exponential backoff from 1s up to 30s on close.
     * - Tracks lastEventId; on reconnect, fetches missed events via
     *   GET /api/pipeline/runs/{id}/events?since=<lastEventId> so the UI
     *   never loses events even if WS drops mid-pipeline.
     * - Returns a control object { close() } — call to stop reconnecting.
     */
    connectWebSocket(runId, onEvent, onClose) {
      let reconnectDelay = 1000;
      let lastEventId = 0;
      let stopped = false;
      let ws = null;

      const open = () => {
        if (stopped) return;
        const token = (typeof getAuthToken === 'function') ? getAuthToken() : '';
        if (!token) {
          console.warn('HQPipeline.connectWebSocket: no auth token');
          return;
        }
        const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
        const url = `${proto}://${location.host}/ws/pipeline/${runId}?token=${encodeURIComponent(token)}`;
        try {
          ws = new WebSocket(url);
        } catch (err) {
          console.warn('HQPipeline WS construct failed:', err);
          scheduleReconnect();
          return;
        }

        ws.addEventListener('open', async () => {
          reconnectDelay = 1000;
          // After reconnect, replay missed events.
          if (lastEventId > 0) {
            try {
              const r = await HQPipeline.getEvents(runId, { since: lastEventId, limit: 200 });
              const newer = (r.events || []).filter(e => e.id > lastEventId);
              // events come DESC; replay chronologically
              newer.reverse().forEach(e => {
                lastEventId = Math.max(lastEventId, e.id);
                if (typeof onEvent === 'function') onEvent(e);
              });
            } catch (err) {
              console.warn('HQPipeline missed-events fetch failed:', err);
            }
          }
        });

        ws.addEventListener('message', (msg) => {
          try {
            const event = JSON.parse(msg.data);
            if (event && event.id) lastEventId = Math.max(lastEventId, event.id);
            if (typeof onEvent === 'function') onEvent(event);
          } catch (err) {
            console.warn('HQPipeline ws parse error:', err);
          }
        });

        ws.addEventListener('close', () => {
          if (stopped) return;
          if (typeof onClose === 'function') {
            try { onClose(); } catch (_) {}
          }
          scheduleReconnect();
        });

        ws.addEventListener('error', () => {
          // Close handler will fire after error → triggers reconnect.
        });
      };

      const scheduleReconnect = () => {
        if (stopped) return;
        const delay = Math.min(reconnectDelay, 30000);
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        setTimeout(open, delay);
      };

      // Allow callers to seed lastEventId so first reconnect doesn't replay
      // already-seen events. (Optional — start fresh if not provided.)
      const ctrl = {
        close: () => {
          stopped = true;
          if (ws) try { ws.close(); } catch (_) {}
        },
        seedLastEventId: (id) => { lastEventId = Math.max(lastEventId, id || 0); },
      };
      open();
      return ctrl;
    },

    // ── Helpers for UI ───────────────────────────────────────────────

    statusLabel(status) {
      const labels = {
        pending: 'Ожидает',
        running: 'Выполняется',
        paused_user: 'Пауза (пользователь)',
        paused_rate_limit: 'Пауза (лимит)',
        awaiting_approval: 'Ждёт approval',
        validating: 'Валидация',
        deploying: 'Деплой',
        review: 'На review',
        done: 'Готово',
        failed: 'Сбой',
        aborted: 'Отменён',
      };
      return labels[status] || status;
    },

    statusColor(status) {
      const colors = {
        pending: 'gray',
        running: 'cyan',
        paused_user: 'yellow',
        paused_rate_limit: 'orange',
        awaiting_approval: 'purple',
        validating: 'blue',
        deploying: 'blue',
        review: 'pink',
        done: 'green',
        failed: 'red',
        aborted: 'gray',
      };
      return colors[status] || 'gray';
    },

    phaseLabel(phase) {
      const labels = {
        prompt: '1. Prompt',
        prd: '2. PRD',
        architecture: '3. Architecture',
        sprints: '4. Sprints',
        execution: '5. Execution',
        validation: '6. Validation',
        handoff: '7. Handoff',
      };
      return labels[phase] || (phase || '—');
    },
  };

  global.HQPipeline = HQPipeline;
})(window);
