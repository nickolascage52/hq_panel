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

    // Pause/resume/abort endpoints — backlog v1.1.
    // Stubs return informative errors so UI can show a TODO toast.
    async pauseRun(id) { throw new Error('Pause endpoint — v1.1 backlog'); },
    async resumeRun(id) { throw new Error('Resume endpoint — v1.1 backlog'); },
    async abortRun(id) { throw new Error('Abort endpoint — v1.1 backlog'); },

    // ── WebSocket live events ────────────────────────────────────────

    /**
     * Connect to /ws/pipeline/{runId} and call onEvent(event) for each frame.
     * Returns the WebSocket instance so callers can close().
     */
    connectWebSocket(runId, onEvent, onClose) {
      const token = (typeof getAuthToken === 'function') ? getAuthToken() : '';
      if (!token) {
        console.warn('HQPipeline.connectWebSocket: no auth token');
        return null;
      }
      const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
      const url = `${proto}://${location.host}/ws/pipeline/${runId}?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      ws.addEventListener('message', (msg) => {
        try {
          const event = JSON.parse(msg.data);
          if (typeof onEvent === 'function') onEvent(event);
        } catch (err) {
          console.warn('HQPipeline ws parse error:', err);
        }
      });
      ws.addEventListener('close', () => {
        if (typeof onClose === 'function') onClose();
      });
      return ws;
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
