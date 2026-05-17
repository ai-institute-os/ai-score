/*!
 * AIScore icon bundle — local Lucide icons
 * Icons: MIT License, Copyright (c) 2020 Lucide Contributors
 * Source: https://github.com/lucide-icons/lucide
 *
 * Provides window.lucide.createIcons() compatible with data-lucide attributes.
 * Icons are loaded from /static/assets/icons/ (SVG files stored locally).
 */
(function (global) {
  'use strict';

  /* SVG inner-content for each icon (24×24 viewBox, stroke-based). */
  var ICONS = {
    'activity':
      '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',

    'alert-triangle':
      '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>' +
      '<line x1="12" x2="12" y1="9" y2="13"/>' +
      '<line x1="12" x2="12.01" y1="17" y2="17"/>',

    'arrow-left':
      '<path d="m12 19-7-7 7-7"/>' +
      '<path d="M19 12H5"/>',

    'arrow-right':
      '<path d="M5 12h14"/>' +
      '<path d="m12 5 7 7-7 7"/>',

    'badge-check':
      '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/>' +
      '<path d="m9 12 2 2 4-4"/>',

    'ban':
      '<circle cx="12" cy="12" r="10"/>' +
      '<line x1="4.93" x2="19.07" y1="4.93" y2="19.07"/>',

    'bar-chart-2':
      '<line x1="18" x2="18" y1="20" y2="10"/>' +
      '<line x1="12" x2="12" y1="20" y2="4"/>' +
      '<line x1="6" x2="6" y1="20" y2="14"/>',

    'building-2':
      '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/>' +
      '<path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>' +
      '<path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/>' +
      '<path d="M10 6h4"/>' +
      '<path d="M10 10h4"/>' +
      '<path d="M10 14h4"/>' +
      '<path d="M10 18h4"/>',

    'calendar-check':
      '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>' +
      '<line x1="16" x2="16" y1="2" y2="6"/>' +
      '<line x1="8" x2="8" y1="2" y2="6"/>' +
      '<line x1="3" x2="21" y1="10" y2="10"/>' +
      '<path d="m9 16 2 2 4-4"/>',

    'calendar-days':
      '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>' +
      '<line x1="16" x2="16" y1="2" y2="6"/>' +
      '<line x1="8" x2="8" y1="2" y2="6"/>' +
      '<line x1="3" x2="21" y1="10" y2="10"/>' +
      '<path d="M8 14h.01"/>' +
      '<path d="M12 14h.01"/>' +
      '<path d="M16 14h.01"/>' +
      '<path d="M8 18h.01"/>' +
      '<path d="M12 18h.01"/>' +
      '<path d="M16 18h.01"/>',

    'check':
      '<path d="M20 6 9 17l-5-5"/>',

    'chevrons-left':
      '<path d="m11 17-5-5 5-5"/>' +
      '<path d="m18 17-5-5 5-5"/>',

    'chevrons-right':
      '<path d="m6 17 5-5-5-5"/>' +
      '<path d="m13 17 5-5-5-5"/>',

    'check-circle-2':
      '<circle cx="12" cy="12" r="10"/>' +
      '<path d="m9 12 2 2 4-4"/>',

    'clock':
      '<circle cx="12" cy="12" r="10"/>' +
      '<polyline points="12 6 12 12 16 14"/>',

    'credit-card':
      '<rect width="20" height="14" x="2" y="5" rx="2"/>' +
      '<line x1="2" x2="22" y1="10" y2="10"/>',

    'download':
      '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' +
      '<polyline points="7 10 12 15 17 10"/>' +
      '<line x1="12" x2="12" y1="15" y2="3"/>',

    'eye':
      '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>' +
      '<circle cx="12" cy="12" r="3"/>',

    'inbox':
      '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>' +
      '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',

    'layout-dashboard':
      '<rect width="7" height="9" x="3" y="3" rx="1"/>' +
      '<rect width="7" height="5" x="14" y="3" rx="1"/>' +
      '<rect width="7" height="9" x="14" y="12" rx="1"/>' +
      '<rect width="7" height="5" x="3" y="16" rx="1"/>',

    'layout-list':
      '<rect width="7" height="7" x="3" y="3" rx="1"/>' +
      '<rect width="7" height="7" x="3" y="14" rx="1"/>' +
      '<path d="M14 4h7"/>' +
      '<path d="M14 9h7"/>' +
      '<path d="M14 15h7"/>' +
      '<path d="M14 20h7"/>',

    'menu':
      '<line x1="4" x2="20" y1="6" y2="6"/>' +
      '<line x1="4" x2="20" y1="12" y2="12"/>' +
      '<line x1="4" x2="20" y1="18" y2="18"/>',

    'mail-open':
      '<path d="M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0l8 6Z"/>' +
      '<path d="m22 10-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 10"/>',

    'microscope':
      '<path d="M6 18h8"/>' +
      '<path d="M3 22h18"/>' +
      '<path d="M14 22a7 7 0 1 0 0-14h-1"/>' +
      '<path d="M9 14h2"/>' +
      '<path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/>' +
      '<path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/>',

    'pencil':
      '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>' +
      '<path d="m15 5 4 4"/>',

    'phone':
      '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.72 13a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.68 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',

    'receipt':
      '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>' +
      '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/>' +
      '<path d="M12 17.5v1.25m0-10v1.25"/>',

    'refresh-cw':
      '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>' +
      '<path d="M21 3v5h-5"/>' +
      '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>' +
      '<path d="M8 16H3v5"/>',

    'search':
      '<circle cx="11" cy="11" r="8"/>' +
      '<path d="m21 21-4.3-4.3"/>',

    'settings-2':
      '<path d="M20 7h-9"/>' +
      '<path d="M14 17H5"/>' +
      '<circle cx="17" cy="17" r="3"/>' +
      '<circle cx="7" cy="7" r="3"/>',

    'target':
      '<circle cx="12" cy="12" r="10"/>' +
      '<circle cx="12" cy="12" r="6"/>' +
      '<circle cx="12" cy="12" r="2"/>',

    'user':
      '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>' +
      '<circle cx="12" cy="7" r="4"/>',

    'users':
      '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>' +
      '<circle cx="9" cy="7" r="4"/>' +
      '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>' +
      '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>',

    'wallet':
      '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/>' +
      '<path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/>' +
      '<path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>',

    'x':
      '<path d="M18 6 6 18"/>' +
      '<path d="m6 6 12 12"/>',

    'x-circle':
      '<circle cx="12" cy="12" r="10"/>' +
      '<path d="m15 9-6 6"/>' +
      '<path d="m9 9 6 6"/>',

    'calendar':
      '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>' +
      '<line x1="16" x2="16" y1="2" y2="6"/>' +
      '<line x1="8" x2="8" y1="2" y2="6"/>' +
      '<line x1="3" x2="21" y1="10" y2="10"/>',

    'check-circle':
      '<circle cx="12" cy="12" r="10"/>' +
      '<path d="m9 12 2 2 4-4"/>',

    'cpu':
      '<rect width="16" height="16" x="4" y="4" rx="2"/>' +
      '<rect width="6" height="6" x="9" y="9" rx="1"/>' +
      '<path d="M15 2v2"/><path d="M15 20v2"/>' +
      '<path d="M2 15h2"/><path d="M2 9h2"/>' +
      '<path d="M20 15h2"/><path d="M20 9h2"/>' +
      '<path d="M9 2v2"/><path d="M9 20v2"/>',

    'file-down':
      '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>' +
      '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>' +
      '<path d="M12 12v6"/>' +
      '<path d="m9 18 3 3 3-3"/>',

    'file-text':
      '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>' +
      '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>' +
      '<path d="M10 9H8"/>' +
      '<path d="M16 13H8"/>' +
      '<path d="M16 17H8"/>',

    'message-square-text':
      '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>' +
      '<path d="M13 8H7"/>' +
      '<path d="M17 12H7"/>',

    'mic':
      '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>' +
      '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>' +
      '<line x1="12" x2="12" y1="19" y2="22"/>',

    'minus-circle':
      '<circle cx="12" cy="12" r="10"/>' +
      '<line x1="8" x2="16" y1="12" y2="12"/>',

    'phone-call':
      '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.72 13a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.68 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>' +
      '<path d="M14.05 2a9 9 0 0 1 8 7.94"/>' +
      '<path d="M14.05 6A5 5 0 0 1 18 10"/>',

    'play':
      '<polygon points="5 3 19 12 5 21 5 3"/>',

    'shield-check':
      '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>' +
      '<path d="m9 12 2 2 4-4"/>',

    'video':
      '<path d="m22 8-6 4 6 4V8z"/>' +
      '<rect width="14" height="12" x="2" y="6" rx="2" ry="2"/>',

    'zap':
      '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  };

  /**
   * Replace all [data-lucide] elements in the document with inline SVGs.
   * Safe to call multiple times — only processes elements still bearing the attribute.
   */
  function createIcons() {
    var els = document.querySelectorAll('[data-lucide]');
    for (var i = 0; i < els.length; i++) {
      var el   = els[i];
      var name = el.getAttribute('data-lucide');
      if (!ICONS[name]) continue;

      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');

      var cls   = el.getAttribute('class');
      var style = el.getAttribute('style');
      if (cls)   svg.setAttribute('class', cls);
      if (style) svg.setAttribute('style', style);

      svg.innerHTML = ICONS[name];
      el.parentNode.replaceChild(svg, el);
    }
  }

  global.lucide = { createIcons: createIcons };

}(typeof window !== 'undefined' ? window : this));
