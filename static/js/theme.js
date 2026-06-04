/**
 * 9Com Theme Manager — theme.js  v1.0
 * Unified dark/light theme for all Django apps
 * Works with Bootstrap 5 (data-bs-theme) and Tailwind pages
 */
(function () {
    'use strict';

    const STORAGE_KEY = '9com-theme';
    const DARK  = 'dark';
    const LIGHT = 'light';

    /** Read preferred theme: localStorage → OS preference → light */
    function getPreferred() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === DARK || saved === LIGHT) return saved;
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return DARK;
        }
        return LIGHT;
    }

    /** Apply theme to <html> element */
    function applyTheme(theme) {
        const html = document.documentElement;
        html.setAttribute('data-theme', theme);
        // Bootstrap 5 dark mode compatibility
        html.setAttribute('data-bs-theme', theme);
        localStorage.setItem(STORAGE_KEY, theme);

        // Update all toggle buttons
        document.querySelectorAll('[data-t-toggle]').forEach(function (btn) {
            const iconEl = btn.querySelector('i, .t-icon');
            if (iconEl) {
                iconEl.className = theme === DARK
                    ? 'fas fa-sun'
                    : 'fas fa-moon';
            }
            btn.setAttribute('title', theme === DARK ? 'Switch to Light' : 'Switch to Dark');
            btn.setAttribute('aria-label', btn.getAttribute('title'));
        });
    }

    /** Toggle between dark and light */
    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || LIGHT;
        applyTheme(current === DARK ? LIGHT : DARK);
    }

    /** Wire up all toggle buttons in the document */
    function wireToggles() {
        document.querySelectorAll('[data-t-toggle]').forEach(function (btn) {
            // Prevent duplicate listeners
            if (btn._themeWired) return;
            btn._themeWired = true;
            btn.addEventListener('click', toggleTheme);
        });
    }

    // ── Init: apply theme immediately (before paint to avoid FOUC) ──
    applyTheme(getPreferred());

    // ── Wire toggles once DOM is ready ──
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireToggles);
    } else {
        wireToggles();
    }

    // ── Listen for OS preference changes ──
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
            // Only auto-switch if user hasn't manually chosen
            if (!localStorage.getItem(STORAGE_KEY)) {
                applyTheme(e.matches ? DARK : LIGHT);
            }
        });
    }

    // ── Expose global API ──
    window.ThemeManager = {
        toggle: toggleTheme,
        set: applyTheme,
        get: function () {
            return document.documentElement.getAttribute('data-theme') || LIGHT;
        }
    };
})();
