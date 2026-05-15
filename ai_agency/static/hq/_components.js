/**
 * HQ — единый sidebar, toast, JSON API helper, mobile nav, авторизация по ролям.
 * Не перезаписывает window.api страниц (там часто возвращается Response).
 *
 * Роли: owner / pm / executor / reviewer
 * Каждый пункт меню имеет roles[] — отображается только тем, у кого роль входит.
 * owner видит всё.
 *
 * ───────────────────────────────────────────────────────────────────────────
 *  TASK MODEL В AI DELIVERY HQ — карта сущностей (P2-4 разметка):
 * ───────────────────────────────────────────────────────────────────────────
 *
 *  kanban_notes   — личные заметки/идеи владельца. Лёгкий канбан, не для команды.
 *                   UI: виджет на dashboard.   API: /api/kanban
 *
 *  tasks_v2       — основной HQ task manager: рабочие задачи владельца с
 *                   приоритетами, дедлайнами, отправкой в AI-команду.
 *                   UI: notes.html, dashboard.   API: /api/tasks-v2
 *
 *  project_tasks  — простые чеклист-задачи внутри CRM-проекта (для клиента).
 *                   Не предназначены для исполнителей-разработчиков.
 *                   UI: crm.html drawer.   API: /api/projects/{id}/tasks
 *
 *  delivery_tasks — производственные задачи: с PR/Preview/Review flow,
 *                   назначением исполнителей, чеклистами и комментариями.
 *                   UI: project-detail.html, my-tasks.html, review.html.
 *                   API: /api/delivery/tasks
 *
 *  tasks          — LEGACY таблица очереди AI-задач (старая система).
 *                   Используется только orchestrator'ом для очереди задач
 *                   к Chief of Staff. В новом коде НЕ использовать.
 *
 *  Правило: каждая UI-страница работает с одной моделью.
 *  Не миксуем — пользователь не должен видеть "общий список задач" из всех таблиц.
 * ───────────────────────────────────────────────────────────────────────────
 */
(function () {
  const SIDEBAR_ITEMS = [
    { href: '/hq/',                  icon: 'layout-dashboard', label: 'Дашборд',     roles: ['owner'] },
    { href: '/hq/delivery.html',     icon: 'package',          label: 'Производство', roles: ['owner','pm','executor','reviewer'] },
    { href: '/hq/executors.html',    icon: 'users-2',         label: 'Исполнители', roles: ['owner','pm'] },
    { href: '/hq/notes.html',        icon: 'layers',           label: 'Задачи', roles: ['owner'] },
    { href: '/hq/knowledge.html',    icon: 'book-open',        label: 'База знаний',  roles: ['owner','pm'] },
    { href: '/hq/crm.html',          icon: 'users',            label: 'CRM',          roles: ['owner','pm'] },
    { href: '/hq/pipeline.html',     icon: 'cpu',              label: 'AI Pipeline',  roles: ['owner'] },
    { href: '/hq/team.html',         icon: 'bot',              label: 'AI Команда (legacy)', roles: ['owner','pm'] },
    { href: '/hq/channel.html',      icon: 'send',             label: 'Канал',        roles: ['owner'] },
    { href: '/hq/analytics.html',    icon: 'bar-chart-2',      label: 'Аналитика',    roles: ['owner'] },
    { href: '/hq/account.html',      icon: 'calendar-check',   label: 'Аккаунт',      roles: ['owner'] },
    { href: '/hq/team-settings.html',icon: 'user-cog',         label: 'Команда',      roles: ['owner'] },
    { href: '/hq/guide.html',        icon: 'book',             label: 'Инструкция',   roles: ['owner','pm','executor','reviewer'] },
    { href: '/hq/settings.html',     icon: 'settings',         label: 'Настройки',    roles: ['owner'] },
  ];

  // ── Авторизация / роли ──

  function getHqPassword() {
    return (
      sessionStorage.getItem('hq_admin_password') ||
      localStorage.getItem('hq_admin_password') ||
      sessionStorage.getItem('hq_password') ||
      localStorage.getItem('hq_password') ||
      ''
    );
  }

  function getAuthToken() {
    return localStorage.getItem('hq_token') || sessionStorage.getItem('hq_token') || '';
  }

  function getCurrentRole() {
    return localStorage.getItem('hq_role') || (getHqPassword() ? 'owner' : '');
  }

  function getCurrentUser() {
    return {
      user_id: parseInt(localStorage.getItem('hq_user_id') || '1', 10),
      role: getCurrentRole(),
      name: localStorage.getItem('hq_user_name') || 'Owner',
    };
  }

  function isAuthenticated() {
    return Boolean(getAuthToken() || getHqPassword());
  }

  // Универсальные заголовки авторизации — отправляем ОБА чтобы backend сам решал.
  // Используется legacy-страницами через window.hqAuthHeaders().
  function hqAuthHeaders() {
    var headers = {};
    var token = getAuthToken();
    var pwd = getHqPassword();
    if (token) headers['X-Auth-Token'] = token;
    if (pwd) headers['X-Admin-Password'] = pwd;
    return headers;
  }

  function logout() {
    const token = getAuthToken();
    if (token) {
      fetch('/api/auth/logout', { method: 'POST', headers: { 'X-Auth-Token': token } })
        .catch(function () {});
    }
    localStorage.removeItem('hq_token');
    localStorage.removeItem('hq_role');
    localStorage.removeItem('hq_user_id');
    localStorage.removeItem('hq_user_name');
    sessionStorage.removeItem('hq_token');
    sessionStorage.removeItem('hq_admin_password');
    localStorage.removeItem('hq_admin_password');
    window.location.href = '/hq/login.html';
  }

  /**
   * Гард: если не авторизован — редирект на login.
   * Возвращает true если можно продолжать.
   * Используется внутренне до DOMContentLoaded.
   */
  function ensureAuthenticated() {
    if (!isAuthenticated()) {
      const here = window.location.pathname + window.location.search;
      // Не редиректим уже на login.html
      if (here.indexOf('/hq/login') === -1) {
        window.location.href = '/hq/login.html?next=' + encodeURIComponent(here);
        return false;
      }
    }
    return true;
  }

  function applyRoleVisibility() {
    const role = getCurrentRole() || 'owner';
    document.querySelectorAll('[data-roles]').forEach(function (el) {
      const allowed = (el.getAttribute('data-roles') || '').split(',').map(function (s) { return s.trim(); });
      if (allowed.indexOf(role) === -1) {
        el.style.display = 'none';
      } else {
        // Снять inline display:none, если был
        if (el.style.display === 'none') el.style.display = '';
      }
    });
  }

  // ── Sidebar ──

  function isSidebarItemActive(path, item) {
    const p = path || '';
    if (item.href === '/hq/' || item.href === '/hq/index.html') {
      return p === '/hq' || p === '/hq/' || p.endsWith('/hq/index.html') || /\/hq\/?$/.test(p);
    }
    const tail = item.href.replace(/^.*\/hq\//, '').replace(/\.html$/, '');
    return tail && (p.includes('/' + tail + '.html') || p.includes('/' + tail + '/'));
  }

  function initSidebar() {
    const nav =
      document.querySelector('.hq-sidebar-nav') ||
      document.querySelector('aside.sidebar nav.nav') ||
      document.querySelector('.sidebar-nav');
    if (!nav) return;
    const path = window.location.pathname;
    const role = getCurrentRole() || 'owner';
    const visible = SIDEBAR_ITEMS.filter(function (item) {
      return !item.roles || item.roles.indexOf(role) !== -1;
    });
    nav.innerHTML = visible.map(function (item) {
      const active = isSidebarItemActive(path, item);
      return (
        '<a href="' +
        item.href +
        '"' +
        (active ? ' class="active"' : '') +
        '><i data-lucide="' +
        item.icon +
        '"></i><span>' +
        item.label +
        '</span></a>'
      );
    }).join('');
    if (window.lucide && typeof lucide.createIcons === 'function') {
      lucide.createIcons();
    }
  }

  // ── Toast ──

  function showToast(msg, type) {
    type = type || 'success';
    var container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'hq-toast-container';
      document.body.appendChild(container);
    }
    var toast = document.createElement('div');
    toast.className = 'hq-toast hq-toast--' + type;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(function () {
      toast.remove();
    }, 3500);
  }

  // ── API helper ──
  // Отправляет ОБА заголовка: X-Auth-Token (новая система) И X-Admin-Password (legacy).
  // Сервер примет любой; так не сломаются страницы с любой стороны.
  async function hqFetchJson(url, method, body) {
    method = method || 'GET';
    var pwd = getHqPassword();
    var token = getAuthToken();
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers['X-Auth-Token'] = token;
    if (pwd) headers['X-Admin-Password'] = pwd;
    var opts = { method: method, headers: headers };
    if (body != null) opts.body = JSON.stringify(body);
    var res = await fetch(url, opts);
    if (res.status === 401) {
      // Сессия мёртвая → на логин
      sessionStorage.removeItem('hq_admin_password');
      window.location.href = '/hq/login.html';
      return null;
    }
    if (res.status === 403) {
      var errBody = {};
      try { errBody = await res.json(); } catch (e) {}
      throw new Error(errBody.detail || 'Нет доступа');
    }
    if (!res.ok) {
      var err = {};
      try {
        err = await res.json();
      } catch (e) {}
      throw new Error(err.detail || err.message || 'HTTP ' + res.status);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  // Алиас apiAuth — короткое имя для новых страниц
  async function apiAuth(url, method, body) {
    return hqFetchJson(url, method, body);
  }

  // ── quickInput (замена prompt) ──

  function quickInput(label, placeholder, callback, defaultVal, allowEmpty) {
    if (typeof defaultVal === 'undefined' || defaultVal === null) defaultVal = '';
    if (typeof allowEmpty === 'undefined') allowEmpty = false;
    function escAttr(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;');
    }
    var existing = document.getElementById('qi-modal');
    if (existing) existing.remove();
    var modal = document.createElement('div');
    modal.id = 'qi-modal';
    modal.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px';
    modal.innerHTML =
      '<div style="background:#1a1a1a;border:1px solid rgba(124,58,237,.35);border-radius:12px;padding:20px;width:360px;max-width:95vw">' +
      '<div id="qi-label" style="font-size:14px;font-weight:600;margin-bottom:12px"></div>' +
      '<input id="qi-inp" type="text" placeholder="' +
      escAttr(placeholder || '') +
      '" value="' +
      escAttr(defaultVal) +
      '" style="width:100%;background:#111;border:1px solid rgba(255,255,255,.12);border-radius:8px;color:#fff;padding:9px 12px;font-size:16px;outline:none;box-sizing:border-box" />' +
      '<div style="display:flex;gap:8px;margin-top:12px">' +
      '<button type="button" id="qi-ok" style="flex:1;background:linear-gradient(135deg,#7c3aed,#a855f7);border:none;border-radius:8px;color:#fff;padding:9px;font-size:13px;font-weight:600;cursor:pointer">OK</button>' +
      '<button type="button" id="qi-cancel" style="background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#a0a0a0;padding:9px 14px;cursor:pointer">Отмена</button>' +
      '</div></div>';
    var labelEl = modal.querySelector('#qi-label');
    if (labelEl) labelEl.textContent = label || '';
    var inp = modal.querySelector('#qi-inp');
    var okBtn = modal.querySelector('#qi-ok');
    var cancelBtn = modal.querySelector('#qi-cancel');
    function close() {
      if (modal && modal.parentNode) modal.parentNode.removeChild(modal);
    }
    okBtn.addEventListener('click', function () {
      var v = inp.value.trim();
      if (!allowEmpty && !v) return;
      close();
      if (callback) callback(v);
    });
    cancelBtn.addEventListener('click', close);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) close();
    });
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        okBtn.click();
      }
      if (e.key === 'Escape') close();
    });
    document.body.appendChild(modal);
    setTimeout(function () {
      if (inp) inp.focus();
    }, 30);
  }

  // ── Mobile nav ──

  var MOBILE_NAV_FALLBACK = [
    { href: '/hq/', icon: 'layout-dashboard', label: 'Главная' },
    { href: '/hq/notes.html', icon: 'check-square', label: 'Задачи' },
    { href: '/hq/crm.html', icon: 'users', label: 'CRM' },
    { href: '/hq/delivery.html', icon: 'package', label: 'Проекты' },
    { href: '/hq/team.html', icon: 'bot', label: 'AI' },
  ];

  function initMobileNav() {
    if (/\/hq\/login(\.html)?$/i.test(window.location.pathname || '')) return;
    var path = window.location.pathname || '';
    var nav =
      document.querySelector('.mobile-bottom-nav') ||
      document.querySelector('.mobile-nav:not(#mobile-nav-bar)') ||
      document.getElementById('mobile-nav-bar');
    if (!nav) {
      nav = document.createElement('nav');
      nav.id = 'mobile-nav-bar';
      nav.className = 'mobile-nav';
      nav.setAttribute('aria-label', 'Основная навигация');
      document.body.appendChild(nav);
      nav.innerHTML = MOBILE_NAV_FALLBACK.map(function (item) {
        var active =
          item.href === '/hq/' || item.href === '/hq/index.html'
            ? path === '/hq/' || path.endsWith('/hq/index.html') || /\/hq\/?$/.test(path)
            : path.indexOf(item.href.replace(/^.*\/hq\//, '').replace(/\.html$/, '')) !== -1;
        return (
          '<a href="' +
          item.href +
          '" class="mobile-nav-item' +
          (active ? ' active' : '') +
          '"><i data-lucide="' +
          item.icon +
          '"></i><span>' +
          item.label +
          '</span></a>'
        );
      }).join('');
    }
    nav.querySelectorAll('.active').forEach(function (x) {
      x.classList.remove('active');
    });
    var markActive = function (item) {
      var page = item.getAttribute('data-page');
      var href = (item.getAttribute('href') || '').split('/').pop() || '';
      var active = false;
      if (page === 'dashboard' || href === 'index.html' || href === '') {
        active =
          path === '/hq' ||
          path === '/hq/' ||
          path.endsWith('/hq/index.html') ||
          /\/hq\/?$/.test(path);
      } else if (page) {
        active = path.indexOf(page) !== -1;
      } else {
        var stem = href.replace(/\.html$/, '');
        if (stem && stem !== 'index') active = path.indexOf(stem) !== -1;
      }
      if (active) item.classList.add('active');
    };
    nav.querySelectorAll('a.mobile-nav-item, .mobile-nav-item[href]').forEach(markActive);
    if (window.lucide && typeof lucide.createIcons === 'function') {
      lucide.createIcons({ nodes: [nav] });
    }
  }

  function initMobileFAB() {
    if (window.innerWidth > 768) return;
    if (document.getElementById('mobile-fab')) return;
    var path = window.location.pathname || '';
    if (/\/hq\/login(\.html)?$/i.test(path)) return;
    var fab = document.createElement('div');
    fab.id = 'mobile-fab';
    fab.style.cssText =
      'position:fixed;right:20px;bottom:calc(74px + env(safe-area-inset-bottom, 0px));z-index:99';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Добавить');
    btn.textContent = '+';
    btn.style.cssText =
      'width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#a855f7);border:none;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 4px 20px rgba(124,58,237,.5);display:flex;align-items:center;justify-content:center';
    btn.addEventListener('click', function () {
      var p = window.location.pathname || '';
      if (p.indexOf('crm') !== -1) {
        var bc = document.getElementById('btnAddClient');
        if (bc) bc.click();
      } else if (p.indexOf('note') !== -1) {
        var bt = document.getElementById('btnCreateTask');
        if (bt) bt.click();
      } else if (p.indexOf('delivery') !== -1) {
        var bp = document.getElementById('btnNewProject');
        if (bp) bp.click();
      }
    });
    if (path.indexOf('crm') === -1 && path.indexOf('note') === -1 && path.indexOf('delivery') === -1) {
      return;
    }
    fab.appendChild(btn);
    document.body.appendChild(fab);
  }

  // ── Глобальный поиск (если уже есть HQV3-поиск в topbar — не дублируем)

  var _searchTimeout = null;
  var _searchOpen = false;

  function initGlobalSearch() {
    var topbarRight = document.querySelector('.topbar-right');
    if (!topbarRight) return;
    if (document.getElementById('global-search-wrap')) return;
    if (topbarRight.querySelector('.hq-topbar-search-wrap')) return;

    var searchWrap = document.createElement('div');
    searchWrap.id = 'global-search-wrap';
    searchWrap.style.cssText = 'position:relative;display:flex;align-items:center';
    searchWrap.innerHTML =
      '<div id="search-toggle" tabindex="0" role="button" aria-label="Поиск"' +
      ' onclick="toggleSearch()" ' +
      ' style="width:32px;height:32px;border-radius:8px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);display:flex;align-items:center;' +
      'justify-content:center;cursor:pointer;transition:all .15s;color:#a0a0a0"' +
      ' onmouseover="this.style.background=&quot;rgba(255,255,255,.1)&quot;"' +
      ' onmouseout="this.style.background=&quot;rgba(255,255,255,.06)&quot;">' +
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></div>' +
      '<div id="search-panel" style="display:none;position:absolute;right:0;top:38px;' +
      'width:360px;background:#1a1a1a;border:1px solid rgba(124,58,237,.3);border-radius:12px;z-index:500;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.5)">' +
      '<div style="padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.06)">' +
      '<input id="search-input" placeholder="Поиск по панели… (мин. 2 символа)" ' +
      'style="width:100%;background:#111;border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#fff;' +
      'padding:8px 12px;font-size:13px;outline:none;box-sizing:border-box"' +
      ' oninput="onSearchInput(this.value)"' +
      ' onkeydown="if(event.key===&quot;Escape&quot;) toggleSearch(false)">' +
      '</div>' +
      '<div id="search-results" style="max-height:320px;overflow-y:auto;padding:6px">' +
      '<div style="color:#606060;font-size:12px;text-align:center;padding:20px">Начните вводить запрос</div></div>' +
      '</div>';

    topbarRight.insertBefore(searchWrap, topbarRight.firstChild);
  }

  function toggleSearch(forceState) {
    _searchOpen = forceState !== undefined ? forceState : !_searchOpen;
    var panel = document.getElementById('search-panel');
    var input = document.getElementById('search-input');
    var results = document.getElementById('search-results');
    if (!panel || !results) return;
    panel.style.display = _searchOpen ? 'block' : 'none';
    if (_searchOpen) {
      setTimeout(function () {
        if (input) input.focus();
      }, 50);
    } else {
      results.innerHTML =
        '<div style="color:#606060;font-size:12px;text-align:center;padding:20px">Начните вводить запрос</div>';
      if (input) input.value = '';
    }
  }

  function onSearchInput(value) {
    clearTimeout(_searchTimeout);
    var results = document.getElementById('search-results');
    if (!results) return;

    if (!value || String(value).trim().length < 2) {
      results.innerHTML =
        '<div style="color:#606060;font-size:12px;text-align:center;padding:20px">Минимум 2 символа</div>';
      return;
    }

    results.innerHTML =
      '<div style="color:#606060;font-size:12px;text-align:center;padding:20px">🔍 Ищем…</div>';

    _searchTimeout = setTimeout(async function () {
      try {
        var qs = encodeURIComponent(value.trim());
        var j = await hqFetchJson('/api/search?q=' + qs);
        var data = Array.isArray(j) ? j : j && Array.isArray(j.results) ? j.results : [];

        if (!data || !data.length) {
          results.innerHTML =
            '<div style="color:#606060;font-size:12px;text-align:center;padding:20px">Ничего не найдено</div>';
          return;
        }

        var typeIcons = {
          client: '👤',
          project: '📁',
          delivery_project: '🚀',
          task: '✅',
          delivery_task: '⚙️',
          knowledge: '📄',
          note: '📝',
          student: '🎓',
        };

        var typeLabels = {
          client: 'Клиент',
          project: 'CRM-проект',
          delivery_project: 'Производство',
          task: 'Задача',
          delivery_task: 'Задача производства',
          knowledge: 'База знаний',
          note: 'Заметка',
          student: 'Ученик',
        };

        var grouped = {};
        data.forEach(function (r) {
          var t = r.type || 'other';
          if (!grouped[t]) grouped[t] = [];
          grouped[t].push(r);
        });

        results.innerHTML = Object.entries(grouped)
          .map(function (entry) {
            var type = entry[0];
            var items = entry[1];
            return (
              '<div style="padding:4px 8px 2px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:#606060">' +
              (typeIcons[type] || '·') +
              ' ' +
              (typeLabels[type] || type) +
              '</div>' +
              items
                .map(function (item) {
                  var sub =
                    item.subtitle || item.preview || '';
                  return (
                    '<a href="' +
                    escapeHtmlHref(item.url || '#') +
                    '" onclick="toggleSearch(false)"' +
                    ' style="display:block;padding:8px 10px;border-radius:8px;text-decoration:none;' +
                    'transition:background .15s;cursor:pointer"' +
                    ' onmouseover="this.style.background=&quot;rgba(255,255,255,.05)&quot;"' +
                    ' onmouseout="this.style.background=&quot;transparent&quot;">' +
                    '<div style="font-size:13px;color:#e0e0e0;font-weight:500">' +
                    escapeHtmlText(item.title || '') +
                    '</div>' +
                    '<div style="font-size:11px;color:#606060;margin-top:2px">' +
                    escapeHtmlText(sub) +
                    '</div>' +
                    '</a>'
                  );
                })
                .join('')
            );
          })
          .join('<div style="height:1px;background:rgba(255,255,255,.04);margin:4px 0"></div>');
      } catch (e) {
        results.innerHTML =
          '<div style="color:#ef4444;font-size:12px;text-align:center;padding:20px">Ошибка: ' +
          escapeHtmlText(e.message || 'запрос') +
          '</div>';
      }
    }, 300);
  }

  function escapeHtmlHref(u) {
    return String(u || '#').replace(/"/g, '&quot;');
  }

  function escapeHtmlText(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  window.toggleSearch = toggleSearch;
  window.onSearchInput = onSearchInput;

  document.addEventListener('click', function (e) {
    var wrap = document.getElementById('global-search-wrap');
    if (wrap && !wrap.contains(e.target) && _searchOpen) {
      toggleSearch(false);
    }
  });

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      toggleSearch();
    }
    if (e.key === 'Escape' && _searchOpen) {
      toggleSearch(false);
    }
  });

  // Гард: на login.html не редиректим
  var isLoginPage = /\/hq\/login(\.html)?$/.test(window.location.pathname);
  if (!isLoginPage) {
    // Синхронный гард до полной загрузки страницы — чтобы не светить контент
    if (!isAuthenticated()) {
      var nextUrl = window.location.pathname + window.location.search;
      window.location.replace('/hq/login.html?next=' + encodeURIComponent(nextUrl));
    }
  }

  // ── Экспорт ──

  window.quickInput = quickInput;

  window.HQShell = {
    SIDEBAR_ITEMS: SIDEBAR_ITEMS,
    getHqPassword: getHqPassword,
    getAuthToken: getAuthToken,
    hqAuthHeaders: hqAuthHeaders,
    getCurrentRole: getCurrentRole,
    getCurrentUser: getCurrentUser,
    isAuthenticated: isAuthenticated,
    ensureAuthenticated: ensureAuthenticated,
    applyRoleVisibility: applyRoleVisibility,
    initSidebar: initSidebar,
    initMobileNav: initMobileNav,
    initMobileFAB: initMobileFAB,
    showToast: showToast,
    hqFetchJson: hqFetchJson,
    apiAuth: apiAuth,
    logout: logout,
  };

  // Удобные глобалы
  window.showToast = showToast;
  window.getHqPassword = getHqPassword;
  window.hqAuthHeaders = hqAuthHeaders;
  window.hqFetchJson = hqFetchJson;
  window.apiAuth = apiAuth;
  window.getCurrentRole = getCurrentRole;
  window.getCurrentUser = getCurrentUser;
  window.applyRoleVisibility = applyRoleVisibility;
  window.hqLogout = logout;

  window.addEventListener('unhandledrejection', function (e) {
    var msg = (e.reason && e.reason.message) ? e.reason.message : String(e.reason || 'Неизвестная ошибка');
    showToast('Ошибка: ' + msg, 'error');
  });

  document.addEventListener('DOMContentLoaded', function () {
    initSidebar();
    applyRoleVisibility();
    initGlobalSearch();
    initMobileNav();
    initMobileFAB();
    if (window.lucide && typeof lucide.createIcons === 'function') {
      lucide.createIcons();
    }
  });
})();
