(function () {
  function getPassword() {
    return (
      sessionStorage.getItem('hq_admin_password') ||
      localStorage.getItem('hq_admin_password') ||
      ''
    );
  }

  async function request(path, options) {
    var opts = options || {};
    var authH = (typeof window.hqAuthHeaders === 'function')
      ? window.hqAuthHeaders()
      : { 'X-Admin-Password': getPassword() };
    var headers = Object.assign({}, authH, opts.headers || {});
    var response = await fetch(path, Object.assign({}, opts, { headers: headers }));
    if (response.status === 401) {
      // Не делаем reload — это вызывает loop когда есть только токен.
      if (!/\/hq\/login(\.html)?$/.test(window.location.pathname)) {
        window.location.href = '/hq/login.html?next=' + encodeURIComponent(window.location.pathname);
      }
    }
    return response;
  }

  async function requestJson(path, options) {
    var response = await request(path, options);
    var data = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      throw new Error(data.detail || data.message || response.statusText || 'Ошибка API');
    }
    return data;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatDate(value) {
    if (!value) return '—';
    var text = String(value).slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return value;
    return text.split('-').reverse().join('.');
  }

  function formatDateTime(value) {
    if (!value) return '—';
    try {
      return new Date(value).toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch (err) {
      return value;
    }
  }

  function getTaskExecutionDate(task) {
    return task.execution_date || task.due_date || '';
  }

  function getTaskDeadline(task) {
    return task.deadline || task.due_date || '';
  }

  function statusMeta(status) {
    var map = {
      'новая': { label: 'Новая', className: 'is-new' },
      'в работе': { label: 'В работе', className: 'is-progress' },
      'на проверке': { label: 'На проверке', className: 'is-review' },
      'готово': { label: 'Готово', className: 'is-done' },
      'отменена': { label: 'Отменена', className: 'is-cancelled' },
    };
    return map[status] || { label: status || 'Без статуса', className: 'is-new' };
  }

  function priorityMeta(priority) {
    var map = {
      'низкий': { label: 'Низкий', className: 'prio-low' },
      'средний': { label: 'Средний', className: 'prio-mid' },
      'высокий': { label: 'Высокий', className: 'prio-high' },
      'критично': { label: 'Критично', className: 'prio-critical' },
    };
    return map[priority] || { label: priority || 'Средний', className: 'prio-mid' };
  }

  async function loadTasks(params) {
    var query = new URLSearchParams();
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value !== undefined && value !== null && value !== '') {
        query.set(key, value);
      }
    });
    var suffix = query.toString() ? '?' + query.toString() : '';
    var data = await requestJson('/api/tasks-v2' + suffix);
    return data.tasks || [];
  }

  async function createTask(payload) {
    return requestJson('/api/tasks-v2', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  async function updateTask(taskId, payload) {
    return requestJson('/api/tasks-v2/' + taskId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  async function sendTaskToTeam(taskId, payload) {
    return requestJson('/api/tasks-v2/' + taskId + '/send-to-team', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
  }

  async function getTask(taskId) {
    return requestJson('/api/tasks-v2/' + taskId);
  }

  async function loadHistory(limit) {
    var query = new URLSearchParams();
    if (limit) query.set('limit', String(limit));
    var suffix = query.toString() ? '?' + query.toString() : '';
    var data = await requestJson('/api/team/tasks-history' + suffix);
    return data.tasks || [];
  }

  window.HQTasks = {
    request: request,
    requestJson: requestJson,
    escapeHtml: escapeHtml,
    formatDate: formatDate,
    formatDateTime: formatDateTime,
    getTaskExecutionDate: getTaskExecutionDate,
    getTaskDeadline: getTaskDeadline,
    statusMeta: statusMeta,
    priorityMeta: priorityMeta,
    loadTasks: loadTasks,
    createTask: createTask,
    updateTask: updateTask,
    sendTaskToTeam: sendTaskToTeam,
    getTask: getTask,
    loadHistory: loadHistory,
  };
})();
