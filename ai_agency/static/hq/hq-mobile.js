/**
 * HQ mobile: активная нижняя навигация.
 */
(function () {
  'use strict';

  function navActive() {
    var path = window.location.pathname.toLowerCase();
    var parts = path.split('/').filter(Boolean);
    var last = parts.length ? parts[parts.length - 1] : '';
    var isDash =
      !last ||
      last === 'index.html' ||
      last === 'hq' ||
      path.endsWith('/hq') ||
      path.endsWith('/hq/');
    document.querySelectorAll('.mobile-nav-item').forEach(function (item) {
      item.classList.remove('active');
      var page = item.dataset.page;
      var on = false;
      if (page === 'dashboard' && isDash) on = true;
      if (page === 'crm' && last.indexOf('crm') !== -1) on = true;
      if (page === 'team' && last.indexOf('team') !== -1) on = true;
      if (page === 'analytics' && last.indexOf('analytics') !== -1) on = true;
      if (page === 'account' && last.indexOf('account') !== -1) on = true;
      if (page === 'channel' && last.indexOf('channel') !== -1) on = true;
      if (page === 'guide' && last.indexOf('guide') !== -1) on = true;
      if (on) item.classList.add('active');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', navActive);
  } else {
    navActive();
  }
})();
