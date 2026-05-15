/**
 * HQ v3 — глобальный поиск, уведомления, FAB (подключать после локального api()/getPw).
 */
(function () {
  const debounce = (fn, ms) => {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  };

  function ensureShellStyles() {
    if (document.getElementById('hq-v3-shell-styles')) return;
    const s = document.createElement('style');
    s.id = 'hq-v3-shell-styles';
    s.textContent = `
      .hq-search-pop { position:absolute; top:100%; right:0; margin-top:6px; width:min(420px,92vw);
        background:var(--hq-card,#1a1a1a); border:1px solid var(--hq-border); border-radius:10px;
        box-shadow:0 12px 40px rgba(0,0,0,.45); z-index:100; max-height:320px; overflow-y:auto; display:none; }
      .hq-search-pop.open { display:block; }
      .hq-search-row { padding:10px 12px; border-bottom:1px solid var(--hq-border); cursor:pointer; font-size:13px; }
      .hq-search-row:hover { background:rgba(124,58,237,.12); }
      .hq-topbar-search-wrap { display:flex; flex-direction:row; align-items:center; gap:8px; position:relative; flex-shrink:0; }
      .hq-topbar-search-wrap .hq-search-toggle { flex-shrink:0; display:inline-flex; align-items:center; justify-content:center; }
      .hq-topbar-search-wrap .hq-search-toggle svg,
      .hq-topbar-search-wrap .hq-search-toggle [data-lucide] {
        width:18px !important; height:18px !important; display:block; flex-shrink:0;
      }
      .hq-topbar-search-wrap .hq-global-search-input {
        display:none;
        box-sizing:border-box;
        width:min(200px,40vw);
        min-width:0;
        min-height:38px;
        margin:0;
        padding:8px 12px;
        line-height:1.45;
        font-size:14px;
        vertical-align:middle;
      }
      .hq-topbar-search-wrap.hq-search-expanded .hq-global-search-input { display:block; }
      @media (max-width:480px){
        .hq-topbar-search-wrap .hq-global-search-input { font-size:16px; }
      }
      .hq-notif-badge { position:absolute; top:-4px; right:-4px; background:#ef4444; color:#fff; font-size:10px;
        min-width:18px; height:18px; border-radius:9px; display:flex; align-items:center; justify-content:center; font-weight:700; }
      .hq-fab { position:fixed; right:calc(16px + env(safe-area-inset-right)); bottom:calc(72px + env(safe-area-inset-bottom));
        width:52px; height:52px; border-radius:50%; background:linear-gradient(135deg,#7c3aed,#a855f7); color:#fff;
        border:none; font-size:22px; cursor:pointer; z-index:200; box-shadow:0 6px 24px rgba(124,58,237,.4);
        display:none; align-items:center; justify-content:center; touch-action:manipulation; }
      @media (max-width:768px){ .hq-fab { display:flex; } }
      .hq-fab-sheet { position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:250; display:none; align-items:flex-end; justify-content:center; }
      .hq-fab-sheet.open { display:flex; }
      .hq-fab-panel { width:100%; max-width:480px; background:var(--hq-sidebar-bg,#111); border-radius:16px 16px 0 0;
        padding:16px; padding-bottom:calc(20px + env(safe-area-inset-bottom)); }
      .hq-fab-panel a { display:block; padding:12px; color:var(--hq-text); text-decoration:none; border-radius:8px; margin-bottom:6px;
        background:rgba(255,255,255,.04); font-size:15px; }
    `;
    document.head.appendChild(s);
  }

  window.HQV3 = {
    initTopbar: function () {
      ensureShellStyles();
      const tr = document.querySelector('.topbar-right');
      if (!tr || tr.querySelector('.hq-v3-inited')) return;
      const legacySearch = document.getElementById('global-search-wrap');
      if (legacySearch) legacySearch.remove();
      tr.classList.add('hq-v3-inited');
      tr.style.position = 'relative';
      tr.style.display = 'flex';
      tr.style.alignItems = 'center';
      tr.style.gap = '10px';

      const wrap = document.createElement('div');
      wrap.className = 'hq-topbar-search-wrap';
      wrap.style.position = 'relative';
      wrap.innerHTML =
        '<button type="button" class="btn btn-ghost btn-icon hq-search-toggle" aria-label="Поиск" title="Поиск">' +
        '<i data-lucide="search" aria-hidden="true"></i></button>' +
        '<input type="text" class="hq-input hq-global-search-input" placeholder="Поиск…" ' +
        'inputmode="search" enterkeyhint="search" autocomplete="off" aria-label="Поиск по HQ" />' +
        '<div class="hq-search-pop" id="hqSearchPop"></div>';
      const notifWrap = document.createElement('div');
      notifWrap.style.position = 'relative';
      notifWrap.innerHTML =
        '<button type="button" class="btn btn-ghost btn-icon hq-notif-btn" aria-label="Уведомления" style="position:relative">' +
        '<i data-lucide="bell" style="width:18px;height:18px"></i><span class="hq-notif-badge" id="hqNotifBadge" style="display:none">0</span></button>' +
        '<div class="hq-search-pop" id="hqNotifPop"></div>';
      tr.insertBefore(wrap, tr.firstChild);
      tr.insertBefore(notifWrap, tr.firstChild.nextSibling);

      const btn = wrap.querySelector('.hq-search-toggle');
      const inp = wrap.querySelector('.hq-global-search-input');
      const pop = wrap.querySelector('#hqSearchPop');
      btn.addEventListener('click', () => {
        wrap.classList.toggle('hq-search-expanded');
        if (wrap.classList.contains('hq-search-expanded')) {
          inp.focus();
          if (typeof lucide !== 'undefined') lucide.createIcons();
        } else {
          pop.classList.remove('open');
        }
      });
      const runSearch = debounce(async () => {
        const q = (inp.value || '').trim();
        if (q.length < 2) {
          pop.classList.remove('open');
          return;
        }
        const api = window.api || window.hqApi;
        if (!api) return;
        const r = await api('/api/search?q=' + encodeURIComponent(q));
        if (!r.ok) return;
        const j = await r.json();
        const rows = (Array.isArray(j) ? j : (j.results || [])).slice(0, 24);
        pop.innerHTML = rows.length
          ? rows
              .map(
                (x) =>
                  '<div class="hq-search-row" data-url="' +
                  String(x.url || '').replace(/"/g, '&quot;') +
                  '"><strong>' +
                  (x.type || '') +
                  '</strong> · ' +
                  (x.title || '').replace(/</g, '&lt;') +
                  '</div>'
              )
              .join('')
          : '<div class="hq-search-row">Ничего не найдено</div>';
        pop.querySelectorAll('.hq-search-row[data-url]').forEach((el) => {
          el.addEventListener('click', () => {
            const u = el.getAttribute('data-url');
            if (u) location.href = u;
          });
        });
        pop.classList.add('open');
      }, 300);
      inp.addEventListener('input', runSearch);

      const nb = document.getElementById('hqNotifBadge');
      const nPop = document.getElementById('hqNotifPop');
      const nBtn = notifWrap.querySelector('.hq-notif-btn');
      async function refreshNotif() {
        const api = window.api || window.hqApi;
        if (!api) return;
        const c = await api('/api/notifications/count');
        if (!c.ok) return;
        const { count } = await c.json();
        if (count > 0) {
          nb.style.display = 'flex';
          nb.textContent = count > 99 ? '99+' : String(count);
        } else {
          nb.style.display = 'none';
        }
      }
      nBtn.addEventListener('click', async () => {
        const api = window.api || window.hqApi;
        if (!api) return;
        const r = await api('/api/notifications?unread=true');
        if (!r.ok) return;
        const j = await r.json();
        const list = (j.notifications || []).slice(0, 5);
        nPop.innerHTML =
          (list.length
            ? list.map((n) => '<div class="hq-search-row">' + (n.title || '').replace(/</g, '&lt;') + '</div>').join('')
            : '<div class="hq-search-row">Нет новых</div>') +
          '<div class="hq-search-row" style="color:var(--hq-accent)">Все уведомления — в разработке</div>';
        nPop.classList.toggle('open');
        await refreshNotif();
      });
      refreshNotif();
      setInterval(refreshNotif, 120000);
      if (typeof lucide !== 'undefined') lucide.createIcons();
    },

    initFab: function () {
      if (document.getElementById('hqFab')) return;
      ensureShellStyles();
      const fab = document.createElement('button');
      fab.type = 'button';
      fab.id = 'hqFab';
      fab.className = 'hq-fab';
      fab.textContent = '+';
      fab.setAttribute('aria-label', 'Быстрые действия');
      const sheet = document.createElement('div');
      sheet.className = 'hq-fab-sheet';
      sheet.id = 'hqFabSheet';
      sheet.innerHTML =
        '<div class="hq-fab-panel" onclick="event.stopPropagation()">' +
        '<div style="font-weight:700;margin-bottom:12px">Быстрые действия</div>' +
        '<a href="crm.html">+ Клиент</a>' +
        '<a href="tasks.html">+ Задача</a>' +
        '<a href="notes.html">+ Заметка</a>' +
        '<a href="team.html">Спросить агента</a>' +
        '<a href="analytics.html">Отчёт / аналитика</a>' +
        '<a href="account.html">Дедлайны</a>' +
        '<button type="button" class="btn btn-ghost" style="width:100%;margin-top:8px" id="hqFabClose">Закрыть</button></div>';
      document.body.appendChild(fab);
      document.body.appendChild(sheet);
      fab.addEventListener('click', () => sheet.classList.add('open'));
      sheet.addEventListener('click', () => sheet.classList.remove('open'));
      sheet.querySelector('#hqFabClose').addEventListener('click', () => sheet.classList.remove('open'));
    },
  };

})();
