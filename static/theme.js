/**
 * Theme manager for Expense Manager.
 * Single palette (Fold's design tokens, id "github" for historical/storage
 * compatibility) with a dark/light mode toggle — no palette picker anymore.
 * Stores mode preference in localStorage.
 */

// SW registration handled by interactions.js

const FIXED_PALETTE = 'github';
const LS_MODE = 'em-mode';

function getSavedPalette() {
  // Always the one remaining palette, regardless of any stale 'em-palette'
  // value a returning browser might still have from before the picker was
  // removed — reading that old value here would set data-theme to an id with
  // no matching CSS block anymore (e.g. "nord-dark"), leaving every --bg/
  // --text/etc. var undefined and the whole app unstyled.
  return FIXED_PALETTE;
}

function getSavedMode() {
  return localStorage.getItem(LS_MODE) || 'dark';
}

function applyTheme(palette, mode) {
  document.documentElement.setAttribute('data-theme', `${palette}-${mode}`);
}

function initTheme() {
  const palette = getSavedPalette();
  const mode = getSavedMode();
  applyTheme(palette, mode);
  return { palette, mode };
}

/**
 * Create and inject the theme picker UI.
 * Call this after the DOM has the .theme-toggle button.
 * Returns a cleanup function (optional).
 */
function initThemePicker(onThemeChange) {
  let { palette, mode } = initTheme();

  const toggle = document.getElementById('theme-toggle');
  if (!toggle) return;

  // Update the mode icon
  function updateIcon() {
    toggle.textContent = mode === 'dark' ? '\u263C' : '\u263E';
  }
  updateIcon();

  // Create the mode picker dropdown \u2014 just dark/light now, no palette choice.
  const picker = document.createElement('div');
  picker.className = 'theme-picker';
  picker.id = 'theme-picker';
  picker.innerHTML = `
    <div class="theme-picker-title">Mode</div>
    <div class="theme-picker-modes">
      <button class="theme-picker-mode ${mode === 'dark' ? 'active' : ''}" data-mode="dark">\u263E Dark</button>
      <button class="theme-picker-mode ${mode === 'light' ? 'active' : ''}" data-mode="light">\u263C Light</button>
    </div>
  `;

  // Insert picker — if toggle is fixed (login/setup), append to body as fixed too
  if (toggle.classList.contains('theme-toggle-fixed')) {
    picker.classList.add('theme-picker-fixed');
    document.body.appendChild(picker);
  } else {
    toggle.parentElement.style.position = 'relative';
    toggle.parentElement.appendChild(picker);
  }

  // Toggle picker visibility
  toggle.addEventListener('click', function(e) {
    e.stopPropagation();
    picker.classList.toggle('open');
  });

  // Close on outside click
  document.addEventListener('click', function(e) {
    if (!picker.contains(e.target) && e.target !== toggle) {
      picker.classList.remove('open');
    }
  });

  picker.addEventListener('click', function(e) {
    const modeBtn = e.target.closest('.theme-picker-mode');

    if (modeBtn) {
      mode = modeBtn.dataset.mode;
      localStorage.setItem(LS_MODE, mode);
      applyTheme(palette, mode);
      updateIcon();
      picker.querySelectorAll('.theme-picker-mode').forEach(el => el.classList.remove('active'));
      modeBtn.classList.add('active');
      if (onThemeChange) onThemeChange();
    }
  });
}
