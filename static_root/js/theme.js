/**
 * 9Com Theme Manager — theme.js  v1.1
 * Unified dark/light theme for all Django apps
 * Works with Bootstrap 5 (data-bs-theme) and Tailwind pages
 */
(function () {
    'use strict';

    var STORAGE_KEY = '9com-theme';
    var LEGACY_KEYS = ['stocks-theme'];   // old per-app keys to migrate
    var DARK  = 'dark';
    var LIGHT = 'light';

    /** Migrate old per-app localStorage keys → unified key */
    function migrateLegacy() {
        if (localStorage.getItem(STORAGE_KEY)) return;   // already set
        for (var i = 0; i < LEGACY_KEYS.length; i++) {
            var val = localStorage.getItem(LEGACY_KEYS[i]);
            if (val === DARK || val === LIGHT) {
                localStorage.setItem(STORAGE_KEY, val);
                return;
            }
        }
    }

    /** Read preferred theme:
     *  1. unified localStorage key
     *  2. legacy per-app keys (migrated above)
     *  3. OS preference
     *  4. DARK (stocks app aesthetic default)
     */
    function getPreferred() {
        migrateLegacy();
        var saved = localStorage.getItem(STORAGE_KEY);
        if (saved === DARK || saved === LIGHT) return saved;
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return DARK;
        }
        return DARK;   // default = dark (premium feel)
    }

    /** Apply theme to <html> element */
    function applyTheme(theme) {
        var html = document.documentElement;
        html.setAttribute('data-theme', theme);
        html.setAttribute('data-bs-theme', theme);    // Bootstrap 5
        localStorage.setItem(STORAGE_KEY, theme);

        // Update icon on all toggle buttons already in DOM
        document.querySelectorAll('[data-t-toggle]').forEach(function (btn) {
            var iconEl = btn.querySelector('i, .t-icon');
            if (iconEl) {
                iconEl.className = theme === DARK ? 'fas fa-sun' : 'fas fa-moon';
            }
        });
    }

    /** Toggle between dark and light */
    function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme') || DARK;
        applyTheme(current === DARK ? LIGHT : DARK);
    }

    /** Wire click listener to every [data-t-toggle] button */
    function wireToggles() {
        document.querySelectorAll('[data-t-toggle]').forEach(function (btn) {
            if (btn._themeWired) return;
            btn._themeWired = true;
            btn.addEventListener('click', toggleTheme);
        });
        // Sync icon with current theme
        var cur = document.documentElement.getAttribute('data-theme') || DARK;
        document.querySelectorAll('[data-t-toggle] i, [data-t-toggle] .t-icon').forEach(function (el) {
            el.className = cur === DARK ? 'fas fa-sun' : 'fas fa-moon';
        });
    }

    // ── 1. Apply theme immediately (before paint) to avoid FOUC ──
    applyTheme(getPreferred());

    // ── 2. Wire toggles after DOM is ready ──
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireToggles);
    } else {
        wireToggles();
    }

    // ── 3. Also wire on full load (catches late-rendered buttons) ──
    window.addEventListener('load', wireToggles);

    // ── 4. OS preference changes (only if user hasn't manually picked) ──
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
            if (!localStorage.getItem(STORAGE_KEY)) {
                applyTheme(e.matches ? DARK : LIGHT);
            }
        });
    }

    // ── 5. Global API ──
    window.ThemeManager = {
        toggle: toggleTheme,
        set:    applyTheme,
        get:    function () {
            return document.documentElement.getAttribute('data-theme') || DARK;
        },
        /** Call after dynamically inserting [data-t-toggle] buttons */
        rewire: wireToggles
    };
})();
