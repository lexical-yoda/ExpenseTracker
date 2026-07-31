/* ═══════════════════════════════════════════════════════════════════════════
   SHARED INTERACTIONS — Expense Manager
   Features: animated counters, toast notifications, pull-to-refresh,
             smooth transitions, auto-refresh, relative timestamps
   ═══════════════════════════════════════════════════════════════════════════ */

// ── 1. Animated counter ──
function animateCounter(el, targetValue, opts = {}) {
  const {
    duration = 400,
    prefix = '',
    suffix = '',
    formatter = null,
    decimals = 0,
  } = opts;

  const startValue = 0;
  const startTime = performance.now();

  // Easing: ease-out cubic
  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const easedProgress = easeOutCubic(progress);
    const currentValue = startValue + (targetValue - startValue) * easedProgress;

    if (formatter) {
      el.textContent = formatter(currentValue);
    } else if (decimals > 0) {
      el.textContent = prefix + currentValue.toFixed(decimals) + suffix;
    } else {
      el.textContent = prefix + Math.round(currentValue).toLocaleString('en-IN') + suffix;
    }

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

// Format as INR
function fmtINR(n) {
  return '₹' + Math.round(n).toLocaleString('en-IN');
}

// Animate a stat element with INR formatting
function animateStat(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  if (typeof value !== 'number' || isNaN(value)) {
    el.textContent = value;
    return;
  }
  animateCounter(el, value, { formatter: fmtINR, duration: 450 });
}


// ── 2. Toast notifications ──
function ensureToastContainer() {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    document.body.appendChild(toast);

    // Inject styles if not present
    if (!document.getElementById('toast-styles')) {
      const style = document.createElement('style');
      style.id = 'toast-styles';
      style.textContent = `
        .toast {
          position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(80px);
          background: var(--surface2); color: var(--text); border: 1px solid var(--border);
          border-radius: 12px; padding: 12px 24px; font-family: var(--font-mono);
          font-size: 0.8rem; z-index: 9999; opacity: 0;
          transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.35s ease;
          pointer-events: none; box-shadow: 0 4px 24px rgba(0,0,0,0.2);
          max-width: 90vw; text-align: center;
        }
        .toast.show { transform: translateX(-50%) translateY(0); opacity: 1; pointer-events: auto; }
        .toast.success { border-color: var(--success); color: var(--success); }
        .toast.error { border-color: var(--danger); color: var(--danger); }
        .toast.info { border-color: var(--accent); color: var(--accent); }
      `;
      document.head.appendChild(style);
    }
  }
  return toast;
}

function showToast(msg, type = 'info') {
  const toast = ensureToastContainer();
  toast.textContent = msg;
  toast.className = `toast ${type} show`;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), 3000);
}


// ── 4. Pull to refresh (mobile) ──
function initPullToRefresh(opts = {}) {
  const { onRefresh = () => location.reload(), threshold = 80 } = opts;
  let startY = 0;
  let pulling = false;

  // Create pull indicator
  const indicator = document.createElement('div');
  indicator.id = 'pull-indicator';
  indicator.innerHTML = '↓ Pull to refresh';
  Object.assign(indicator.style, {
    position: 'fixed', top: '-50px', left: '50%', transform: 'translateX(-50%)',
    background: 'var(--surface2)', color: 'var(--muted)', border: '1px solid var(--border)',
    borderRadius: '24px', padding: '8px 20px', fontSize: '0.72rem',
    fontFamily: 'var(--font-mono)', zIndex: '9998',
    transition: 'top 0.3s ease, opacity 0.3s ease', opacity: '0',
    textTransform: 'uppercase', letterSpacing: '0.5px',
  });
  document.body.appendChild(indicator);

  document.addEventListener('touchstart', (e) => {
    if (window.scrollY === 0) {
      startY = e.touches[0].clientY;
      pulling = true;
    }
  }, { passive: true });

  document.addEventListener('touchmove', (e) => {
    if (!pulling) return;
    const diff = e.touches[0].clientY - startY;
    if (diff > 10 && diff < threshold * 2) {
      const progress = Math.min(diff / threshold, 1);
      indicator.style.top = (diff * 0.4 - 10) + 'px';
      indicator.style.opacity = progress;
      indicator.innerHTML = diff >= threshold ? '↑ Release to refresh' : '↓ Pull to refresh';
    }
  }, { passive: true });

  document.addEventListener('touchend', () => {
    if (!pulling) return;
    pulling = false;
    const wasReady = indicator.innerHTML.includes('Release');
    indicator.style.top = '-50px';
    indicator.style.opacity = '0';
    if (wasReady) {
      indicator.innerHTML = 'Refreshing...';
      indicator.style.top = '10px';
      indicator.style.opacity = '1';
      onRefresh();
    }
  }, { passive: true });
}


// ── 5. Stat card stagger animation ──
// Add CSS for stat card transitions
(function() {
  const style = document.createElement('style');
  style.textContent = `
    .stats-row .stat-card, .chart-card, .acct-bal-card {
      transition: opacity 0.15s ease, transform 0.15s ease;
    }
    .fade-in .stat-card, .fade-in .chart-card, .fade-in .acct-bal-card {
      animation: slideUp 0.2s ease forwards;
      opacity: 0;
    }
    @keyframes slideUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .fade-in .stat-card:nth-child(1) { animation-delay: 0s; }
    .fade-in .stat-card:nth-child(2) { animation-delay: 0.02s; }
    .fade-in .stat-card:nth-child(3) { animation-delay: 0.04s; }
    .fade-in .stat-card:nth-child(4) { animation-delay: 0.06s; }
    .fade-in .stat-card:nth-child(5) { animation-delay: 0.08s; }
    .fade-in .stat-card:nth-child(6) { animation-delay: 0.1s; }
    .fade-in .acct-bal-card:nth-child(1) { animation-delay: 0.04s; }
    .fade-in .acct-bal-card:nth-child(2) { animation-delay: 0.06s; }
    .fade-in .acct-bal-card:nth-child(3) { animation-delay: 0.08s; }
    .fade-in .acct-bal-card:nth-child(4) { animation-delay: 0.1s; }
  `;
  document.head.appendChild(style);
})();

function triggerFadeIn(selector) {
  const el = document.querySelector(selector);
  if (!el) return;
  el.classList.remove('fade-in');
  void el.offsetWidth; // Force reflow
  el.classList.add('fade-in');
}


// ── 6. Auto-refresh ──
function initAutoRefresh(opts = {}) {
  const { interval = 60000, onRefresh } = opts;
  let timer = null;
  let paused = false;

  function start() {
    stop();
    timer = setInterval(() => {
      if (!paused && !document.hidden) {
        if (onRefresh) {
          onRefresh();
        }
      }
    }, interval);
  }

  function stop() {
    if (timer) clearInterval(timer);
  }

  // Pause when tab is hidden
  document.addEventListener('visibilitychange', () => {
    paused = document.hidden;
  });

  start();
  return { start, stop };
}


// ── PWA Service Worker Registration ──
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .catch(() => {}); // Silently fail if not HTTPS
  });
}


// ── 8. Help icons (small "?" tooltips explaining pages/buttons/workflows) ──
// Usage: <span class="help-icon" tabindex="0" role="button" aria-label="Help"
//         data-help="Explanation text goes here">?</span>
// Self-initializing via event delegation — works for icons added dynamically
// later (e.g. rows built via innerHTML), no per-page init call needed.
(function() {
  const style = document.createElement('style');
  style.textContent = `
    .help-icon {
      display: inline-flex; align-items: center; justify-content: center;
      width: 15px; height: 15px; border-radius: 50%;
      background: var(--surface2); color: var(--muted); border: 1px solid var(--border);
      font-size: 0.62rem; font-weight: 700; cursor: help; user-select: none;
      position: relative; flex-shrink: 0; margin-left: 5px; vertical-align: middle;
      line-height: 1;
    }
    .help-icon:hover, .help-icon:focus { color: var(--accent); border-color: var(--accent); outline: none; }
    .help-popover {
      position: absolute; z-index: 10000; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
      background: var(--surface2); color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 10px 12px; font-size: 0.75rem; line-height: 1.45;
      width: max-content; max-width: 240px; text-align: left; cursor: auto;
      box-shadow: 0 4px 16px rgba(0,0,0,0.25); white-space: normal;
    }
    .help-popover::after {
      content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
      border: 5px solid transparent; border-top-color: var(--border);
    }
    @media (max-width: 480px) {
      .help-popover { left: 0; transform: none; max-width: 200px; }
      .help-popover::after { left: 12px; transform: none; }
    }
  `;
  document.head.appendChild(style);

  document.addEventListener('click', function(e) {
    const icon = e.target.closest('.help-icon');
    // help-icon is often placed inside a <label for="...">; without this, the
    // browser's native label-click forwards a second synthetic click to the
    // associated form control, which bubbles back to this same listener and
    // immediately closes the popover this click just opened.
    if (icon) e.preventDefault();
    const openPopover = document.querySelector('.help-popover');
    const wasThisIconOpen = !!(openPopover && icon && openPopover.parentElement === icon);
    if (openPopover) openPopover.remove();
    if (icon && icon.dataset.help && !wasThisIconOpen) {
      e.stopPropagation();
      const pop = document.createElement('div');
      pop.className = 'help-popover';
      pop.textContent = icon.dataset.help;
      icon.appendChild(pop);
    }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      if (document.activeElement && document.activeElement.classList.contains('help-icon')) {
        e.preventDefault();
        document.activeElement.click();
      }
    } else if (e.key === 'Escape') {
      const p = document.querySelector('.help-popover');
      if (p) p.remove();
    }
  });
})();


// ── 9. Shared search predicate ──
// Used by both manage.html's own #search field and the Cmd+K global overlay
// below, so the two can never disagree about what "matches" a query.
function matchesSearchQuery(description, category, query) {
  const q = (query || '').toLowerCase().trim();
  if (!q) return true;
  return (description || '').toLowerCase().includes(q) || (category || '').toLowerCase().includes(q);
}


// ── 10. Cmd+K global search ──
// Self-initializing (like the help-icons feature above) — works on every page
// that loads interactions.js, no per-page init call needed. Fetches
// /api/transactions lazily (only when the overlay is first opened, not on
// every page load) and filters client-side with the same predicate manage.html
// uses. Selecting a result or pressing Enter navigates to
// /manage?search=<query>, which manage.html's own URL-param handling picks up
// (same pattern already used there for ?date= from dashboard chart clicks).
(function() {
  let overlay = null;
  let inputEl = null;
  let resultsEl = null;
  let allTxns = null; // fetched lazily, cached for the life of the page
  let activeIndex = -1;
  let previouslyFocused = null; // for focus-return on close

  function injectStyles() {
    if (document.getElementById('cmdk-styles')) return;
    const style = document.createElement('style');
    style.id = 'cmdk-styles';
    style.textContent = `
      .cmdk-backdrop {
        position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 10000;
        display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh;
      }
      .cmdk-panel {
        background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
        width: 90vw; max-width: 520px; max-height: 60vh; overflow: hidden;
        display: flex; flex-direction: column; box-shadow: 0 16px 48px rgba(0,0,0,0.4);
      }
      .cmdk-input {
        width: 100%; background: none; border: none; border-bottom: 1px solid var(--border);
        color: var(--text); font-family: var(--font-mono); font-size: 0.95rem;
        padding: 16px 18px; outline: none;
      }
      .cmdk-results { overflow-y: auto; }
      .cmdk-empty { padding: 20px 18px; color: var(--muted); font-size: 0.8rem; text-align: center; }
      .cmdk-row {
        display: flex; align-items: center; gap: 10px; padding: 10px 18px;
        cursor: pointer; font-size: 0.82rem; border-bottom: 1px solid var(--border);
      }
      .cmdk-row:last-child { border-bottom: none; }
      .cmdk-row:hover, .cmdk-row.active { background: var(--surface2); }
      .cmdk-row-desc { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
      .cmdk-row-meta { color: var(--muted); font-size: 0.68rem; flex-shrink: 0; }
      .cmdk-row-amount { font-family: var(--font-display); font-weight: 600; flex-shrink: 0; }
      .cmdk-hint {
        padding: 8px 18px; font-size: 0.65rem; color: var(--muted);
        border-top: 1px solid var(--border); text-transform: uppercase; letter-spacing: 0.5px;
      }
    `;
    document.head.appendChild(style);
  }

  function fmtAmt(n) {
    return '₹' + Math.round(n).toLocaleString('en-IN');
  }

  function renderResults(query) {
    const q = query.trim();
    if (!q) {
      resultsEl.innerHTML = '<div class="cmdk-empty">Type to search transactions by description or category…</div>';
      activeIndex = -1;
      return;
    }
    const matches = allTxns
      .filter(t => !t.parent_id && matchesSearchQuery(t.description, t.category, q))
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, 8);
    if (matches.length === 0) {
      resultsEl.innerHTML = '<div class="cmdk-empty">No matching transactions</div>';
      activeIndex = -1;
      return;
    }
    const esc = s => { const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML; };
    resultsEl.innerHTML = matches.map((t, i) => {
      const sign = t.type === 'Income' ? '+' : t.type === 'Transfer' ? '⇄' : '-';
      // Description isn't put in an HTML attribute here (textContent->innerHTML
      // escaping handles &/</> for text nodes but not quote characters, which
      // would break out of an attribute value) — set as a DOM property instead
      // right after insertion, below, which is quote-safe regardless of content.
      return `<div class="cmdk-row${i === 0 ? ' active' : ''}" role="option" id="cmdk-opt-${i}" aria-selected="${i === 0}">
        <span class="cmdk-row-desc">${esc(t.description)}</span>
        <span class="cmdk-row-meta">${esc(t.category)} · ${esc(t.date)}</span>
        <span class="cmdk-row-amount">${sign}${fmtAmt(t.amount)}</span>
      </div>`;
    }).join('');
    Array.from(resultsEl.querySelectorAll('.cmdk-row')).forEach((row, i) => {
      row.dataset.desc = matches[i].description;
    });
    activeIndex = 0;
    if (matches.length) inputEl.setAttribute('aria-activedescendant', 'cmdk-opt-0');
    else inputEl.removeAttribute('aria-activedescendant');
  }

  function goToManage(query) {
    window.location.href = '/manage?search=' + encodeURIComponent(query);
  }

  function openOverlay() {
    injectStyles();
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'cmdk-backdrop';
      overlay.innerHTML = `
        <div class="cmdk-panel" role="dialog" aria-modal="true" aria-label="Search transactions">
          <input class="cmdk-input" type="text" placeholder="Search transactions…" autocomplete="off"
                 aria-label="Search transactions by description or category" role="combobox"
                 aria-expanded="true" aria-controls="cmdk-results-list" aria-autocomplete="list">
          <div class="cmdk-results" id="cmdk-results-list" role="listbox" aria-label="Search results"></div>
          <div class="cmdk-hint">Esc to close · Enter to jump to Manage</div>
        </div>`;
      document.body.appendChild(overlay);
      inputEl = overlay.querySelector('.cmdk-input');
      resultsEl = overlay.querySelector('.cmdk-results');

      overlay.addEventListener('click', (e) => { if (e.target === overlay) closeOverlay(); });
      inputEl.addEventListener('input', () => renderResults(inputEl.value));
      resultsEl.addEventListener('click', (e) => {
        const row = e.target.closest('.cmdk-row');
        if (row) goToManage(row.dataset.desc);
      });
      inputEl.addEventListener('keydown', (e) => {
        const rows = () => Array.from(resultsEl.querySelectorAll('.cmdk-row'));
        if (e.key === 'Escape') { e.preventDefault(); closeOverlay(); }
        else if (e.key === 'Tab') {
          // Single-field dialog — the input is the only natively focusable
          // element inside it, so Tab/Shift+Tab just re-focuses it instead of
          // moving focus to whatever's behind the overlay in the page.
          e.preventDefault();
          inputEl.focus();
        }
        else if (e.key === 'ArrowDown') {
          e.preventDefault();
          const r = rows(); if (!r.length) return;
          activeIndex = Math.min(activeIndex + 1, r.length - 1);
          r.forEach((el, i) => {
            el.classList.toggle('active', i === activeIndex);
            el.setAttribute('aria-selected', String(i === activeIndex));
          });
          inputEl.setAttribute('aria-activedescendant', r[activeIndex].id);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          const r = rows(); if (!r.length) return;
          activeIndex = Math.max(activeIndex - 1, 0);
          r.forEach((el, i) => {
            el.classList.toggle('active', i === activeIndex);
            el.setAttribute('aria-selected', String(i === activeIndex));
          });
          inputEl.setAttribute('aria-activedescendant', r[activeIndex].id);
        } else if (e.key === 'Enter') {
          e.preventDefault();
          const r = rows();
          const active = r[activeIndex] || r[0];
          if (active) goToManage(active.dataset.desc);
          else if (inputEl.value.trim()) goToManage(inputEl.value);
        }
      });
    }
    previouslyFocused = document.activeElement;
    overlay.style.display = 'flex';
    inputEl.value = '';
    inputEl.focus();
    renderResults('');

    if (!allTxns) {
      resultsEl.innerHTML = '<div class="cmdk-empty">Loading…</div>';
      fetch('/api/transactions')
        .then(r => r.json())
        .then(data => { allTxns = Array.isArray(data) ? data : []; renderResults(inputEl.value); })
        .catch(() => { resultsEl.innerHTML = '<div class="cmdk-empty">Couldn\'t load transactions</div>'; });
    }
  }

  function closeOverlay() {
    if (overlay) overlay.style.display = 'none';
    if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
      previouslyFocused.focus();
    }
    previouslyFocused = null;
  }

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (overlay && overlay.style.display === 'flex') closeOverlay();
      else openOverlay();
    }
  });
})();


// ── 7. Relative timestamps ──
function timeAgo(dateStr) {
  // Compare calendar dates to avoid timezone/time-of-day issues
  const target = new Date(dateStr + 'T00:00:00');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDay = Math.round((today - target) / 86400000);

  if (diffDay === 0) return 'Today';
  if (diffDay === 1) return 'Yesterday';
  if (diffDay < 7) return diffDay + ' days ago';
  if (diffDay < 14) return '1 week ago';
  if (diffDay < 30) return Math.floor(diffDay / 7) + ' weeks ago';
  if (diffDay < 60) return '1 month ago';
  return Math.floor(diffDay / 30) + ' months ago';
}


