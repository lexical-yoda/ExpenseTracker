/**
 * Theme manager for Expense Manager.
 * Handles palette selection (github, indigo, nord, etc.) and mode (dark/light).
 * Stores preference in localStorage.
 */

const THEMES = [
  { id: 'github',  label: 'GitHub' },
  { id: 'indigo',  label: 'Indigo' },
  { id: 'nord',    label: 'Nord' },
  { id: 'emerald', label: 'Emerald' },
  { id: 'rose',    label: 'Rose' },
  { id: 'amber',   label: 'Amber' },
  { id: 'ocean',   label: 'Ocean' },
];

const LS_PALETTE = 'em-palette';
const LS_MODE = 'em-mode';

function getSavedPalette() {
  return localStorage.getItem(LS_PALETTE) || 'github';
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

  // Create the palette picker dropdown
  const picker = document.createElement('div');
  picker.className = 'theme-picker';
  picker.id = 'theme-picker';
  picker.innerHTML = `
    <div class="theme-picker-title">Theme</div>
    ${THEMES.map(t => `
      <button class="theme-picker-item ${t.id === palette ? 'active' : ''}" data-palette="${t.id}">
        <span class="theme-picker-dot"></span>
        ${t.label}
      </button>
    `).join('')}
    <div class="theme-picker-divider"></div>
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

  // Palette selection
  picker.addEventListener('click', function(e) {
    const item = e.target.closest('.theme-picker-item');
    const modeBtn = e.target.closest('.theme-picker-mode');

    if (item) {
      palette = item.dataset.palette;
      localStorage.setItem(LS_PALETTE, palette);
      applyTheme(palette, mode);
      // Update active states
      picker.querySelectorAll('.theme-picker-item').forEach(el => el.classList.remove('active'));
      item.classList.add('active');
      if (onThemeChange) onThemeChange();
    }

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
