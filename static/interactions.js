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


