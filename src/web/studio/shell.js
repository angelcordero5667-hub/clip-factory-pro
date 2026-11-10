/* Clip Factory Pro — AI Creative Studio · FASE 3: ApplicationShell + Navigation + router
 *
 * Se carga solo con ?ui=studio (ver index.html). No reemplaza ninguna lógica existente:
 * las vistas actuales (view-*) siguen siendo el área de trabajo y se navega con el
 * switchView() que ya existe. Los datos (cola, proyecto) salen de /api/jobs y del
 * selector de proyecto real. No hay valores simulados.
 */
(function () {
  'use strict';
  if (!document.documentElement.classList.contains('cf-studio')) return;

  // ---------- utilidades mínimas (sin innerHTML con datos) ----------
  const SVG_NS = 'http://www.w3.org/2000/svg';
  function el(tag, props, children) {
    const n = document.createElement(tag);
    if (props) for (const k in props) {
      if (k === 'class') n.className = props[k];
      else if (k === 'text') n.textContent = props[k];
      else if (k === 'on') for (const ev in props.on) n.addEventListener(ev, props.on[ev]);
      else n.setAttribute(k, props[k]);
    }
    (children || []).forEach(c => c && n.appendChild(c));
    return n;
  }
  function icon(paths) {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
    paths.forEach(d => { const p = document.createElementNS(SVG_NS, 'path'); p.setAttribute('d', d); s.appendChild(p); });
    return s;
  }
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  };

  // ---------- mapa de rutas → funcionalidad EXISTENTE ----------
  // view: sección actual que se muestra · focus/scroll: dónde situar al usuario
  // action: función existente (para Settings, que ya es un modal real)
  const ROUTES = [
    { id: 'home',       label: 'Home',       sub: 'Tu espacio de trabajo',            view: 'inicio',   ico: ['M3 11l9-8 9 8', 'M5 10v10h14V10', 'M10 20v-6h4v6'] },
    { id: 'create',     label: 'Create',     sub: 'Importar y analizar un video',     view: 'inicio',   focus: '#yt-url-input', ico: ['M12 5v14', 'M5 12h14'] },
    { id: 'editor',     label: 'Editor',     sub: 'Subtítulos, estilos y re-render',  view: 'editor',   ico: ['M4 20l4-1 11-11-3-3L5 16z', 'M14 6l3 3'] },
    { id: 'clips',      label: 'Clips',      sub: 'Contenido generado',               view: 'inicio',   scroll: '#carousel-proyectos', ico: ['M4 5h16v14H4z', 'M10 9l5 3-5 3z'] },
    { id: 'ai',         label: 'AI Tools',   sub: 'Ganchos, copys y miniaturas',      view: 'copys',    ico: ['M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z', 'M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z'] },
    { id: 'projects',   label: 'Projects',   sub: 'Videos fuente y paquetes',         view: 'proyectos', ico: ['M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z'] },
    { id: 'processing', label: 'Processing', sub: 'Trabajos y cola',                  view: 'historial', ico: ['M12 3v4', 'M12 17v4', 'M3 12h4', 'M17 12h4', 'M5.6 5.6l2.8 2.8', 'M15.6 15.6l2.8 2.8', 'M5.6 18.4l2.8-2.8', 'M15.6 8.4l2.8-2.8'] },
    { id: 'analytics',  label: 'Analytics',  sub: 'Métricas reales del sistema',      view: 'analytics', ico: ['M4 20V10', 'M10 20V4', 'M16 20v-8', 'M22 20H2'] },
    { id: 'settings',   label: 'Settings',   sub: 'Hardware, modelos y exportación',  action: 'openSettingsModal', ico: ['M12 15a3 3 0 100-6 3 3 0 000 6z', 'M19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.4 1a7 7 0 00-2-1.2L14 3h-4l-.4 2.7a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.5A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.4-1a7 7 0 002 1.2L10 21h4l.4-2.7a7 7 0 002-1.2l2.4 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z'] },
  ];
  const MOBILE_TABS = ['home', 'create', 'clips', 'processing']; // + "Más"
  const byId = Object.fromEntries(ROUTES.map(r => [r.id, r]));

  let current = 'home';

  // ---------- router ----------
  function go(routeId) {
    const r = byId[routeId]; if (!r) return;
    closeSheet();
    if (r.action) {
      if (typeof window[r.action] === 'function') window[r.action]();
      return;
    }
    current = routeId;
    if (typeof window.switchView === 'function') window.__cfRealSwitch(r.view);
    paint();
    // situar al usuario donde corresponde dentro de la vista existente
    requestAnimationFrame(() => {
      if (r.focus) { const t = document.querySelector(r.focus); if (t) { t.scrollIntoView({ block: 'center', behavior: 'smooth' }); t.focus({ preventScroll: true }); } }
      else if (r.scroll) { const t = document.querySelector(r.scroll); if (t) t.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
    });
    try { history.replaceState(null, '', '?ui=studio#/' + routeId); } catch (e) {}
  }

  // Si el JS antiguo cambia de vista por su cuenta (botones internos), el shell lo sigue.
  window.__cfRealSwitch = window.switchView;
  window.switchView = function (view) {
    window.__cfRealSwitch(view);
    const keep = byId[current] && byId[current].view === view;
    if (!keep) {
      const match = ROUTES.find(r => r.view === view && !r.focus && !r.scroll);
      if (match) current = match.id;
    }
    paint();
  };

  // ---------- construcción del shell ----------
  const railBtns = {}, tabBtns = {};
  const barTitle = el('div', { class: 'cf-bar-title' });
  const barSub = el('div', { class: 'cf-bar-sub' });
  const projLabel = el('span', { text: 'Sin proyecto' });
  const projChip = el('button', { class: 'cf-chip', type: 'button', title: 'Proyecto activo · abrir Projects', on: { click: () => go('projects') } }, [
    icon(['M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z']), projLabel]);
  projChip.firstChild.style.cssText = 'width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:1.7;flex:none';
  const statusLabel = el('span', { text: 'Cola: …' });
  const statusChip = el('button', { class: 'cf-chip cf-status', type: 'button', 'data-state': 'idle', title: 'Ver trabajos en Processing', on: { click: () => go('processing') } }, [el('i', { class: 'cf-dot' }), statusLabel]);
  const newBtn = el('button', { class: 'cf-btn-primary', type: 'button', text: 'Nuevo proyecto', on: { click: () => go('create') } });

  function navButton(r, labelled) {
    const b = el('button', { class: 'cf-nav-btn', type: 'button', 'aria-label': r.label, title: r.label, on: { click: () => go(r.id) } }, [icon(r.ico), el('span', { class: 'cf-nav-label', text: r.label })]);
    return b;
  }

  const rail = el('nav', { class: 'cf-rail', 'aria-label': 'Navegación principal' });
  rail.appendChild(el('div', { class: 'cf-brand' }, [
    el('div', { class: 'cf-brand-mark', text: 'CF', 'aria-hidden': 'true' }),
    el('div', { class: 'cf-brand-name cf-nav-label' }, [document.createTextNode('Clip Factory Pro'), el('small', { text: 'AI Video Studio' })]),
  ]));
  ROUTES.filter(r => r.id !== 'settings').forEach(r => { const b = navButton(r); railBtns[r.id] = b; rail.appendChild(b); });
  rail.appendChild(el('div', { class: 'cf-nav-spacer' }));
  { const b = navButton(byId.settings); railBtns.settings = b; rail.appendChild(b); }
  const toggle = el('button', { class: 'cf-nav-btn cf-rail-toggle', type: 'button', 'aria-label': 'Expandir o contraer navegación', title: 'Expandir / contraer',
    on: { click: () => { const open = document.documentElement.classList.toggle('cf-rail-open'); store.set('cf_rail_open', open ? '1' : '0'); } } },
    [icon(['M9 6l6 6-6 6']), el('span', { class: 'cf-nav-label', text: 'Contraer' })]);
  rail.appendChild(toggle);

  const bar = el('header', { class: 'cf-bar' }, [
    el('div', { style: 'display:flex;flex-direction:column;gap:5px;min-width:0' }, [barTitle, barSub]),
    el('div', { class: 'cf-bar-spacer' }), projChip, statusChip, newBtn]);

  // móvil: barra inferior + hoja "Más"
  const tabbar = el('nav', { class: 'cf-tabbar', 'aria-label': 'Navegación móvil' });
  MOBILE_TABS.forEach(id => {
    const r = byId[id];
    const t = el('button', { class: 'cf-tab', type: 'button', on: { click: () => go(id) } }, [icon(r.ico), el('span', { text: r.label })]);
    tabBtns[id] = t; tabbar.appendChild(t);
  });
  const moreBtn = el('button', { class: 'cf-tab', type: 'button', 'aria-label': 'Más secciones', on: { click: openSheet } },
    [icon(['M5 12h.01', 'M12 12h.01', 'M19 12h.01']), el('span', { text: 'Más' })]);
  tabbar.appendChild(moreBtn);
  const sheet = el('div', { class: 'cf-sheet', role: 'dialog', 'aria-label': 'Más secciones' });
  ROUTES.filter(r => !MOBILE_TABS.includes(r.id)).forEach(r => { sheet.appendChild(navButton(r)); });
  const sheetBackdrop = el('div', { class: 'cf-sheet-backdrop', on: { click: closeSheet } });
  function openSheet() { document.documentElement.classList.add('cf-sheet-open'); }
  function closeSheet() { document.documentElement.classList.remove('cf-sheet-open'); }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });

  document.body.append(rail, bar, tabbar, sheetBackdrop, sheet);
  if (store.get('cf_rail_open') === '1') document.documentElement.classList.add('cf-rail-open');

  // ---------- pintado de estado ----------
  function paint() {
    const r = byId[current] || ROUTES[0];
    barTitle.textContent = r.label;
    barSub.textContent = r.sub;
    document.title = r.label + ' · Clip Factory Pro';
    [railBtns, tabBtns].forEach(group => {
      for (const id in group) {
        if (id === current) group[id].setAttribute('aria-current', 'page'); else group[id].removeAttribute('aria-current');
      }
    });
    moreBtn.removeAttribute('aria-current');
    if (!MOBILE_TABS.includes(current) && current !== 'settings') moreBtn.setAttribute('aria-current', 'page');
  }

  // Proyecto activo: el selector real del panel (#global-project-select)
  function syncProject() {
    const sel = document.getElementById('global-project-select');
    let name = '';
    if (sel && sel.value) { const o = sel.options[sel.selectedIndex]; name = o ? o.textContent.trim() : ''; }
    projLabel.textContent = name || 'Sin proyecto activo';
  }

  // Estado de cola real: /api/jobs (queued / running / done / error / cancelled)
  async function syncQueue() {
    try {
      const res = await fetch('/api/jobs');
      if (!res.ok) throw new Error(res.status);
      const jobs = await res.json();
      const running = jobs.filter(j => j.status === 'running');
      const queued = jobs.filter(j => j.status === 'queued');
      if (running.length) {
        const j = running[0];
        const pct = Math.round((Number(j.progress) || 0) * 100);
        statusChip.dataset.state = 'running';
        statusLabel.textContent = '#' + j.id + ' · ' + (j.step_label || 'Procesando') + ' ' + pct + '%' + (queued.length ? ' · +' + queued.length : '');
      } else if (queued.length) {
        statusChip.dataset.state = 'queued';
        statusLabel.textContent = queued.length + ' en espera';
      } else {
        statusChip.dataset.state = 'idle';
        statusLabel.textContent = 'Sin trabajos activos';
      }
    } catch (e) {
      statusChip.dataset.state = 'error';
      statusLabel.textContent = 'Cola no disponible';
    }
  }

  // arranque: ruta desde el hash, si es válida
  const fromHash = (location.hash.match(/^#\/(\w+)/) || [])[1];
  if (fromHash && byId[fromHash] && !byId[fromHash].action) { current = fromHash; window.__cfRealSwitch(byId[fromHash].view); }
  paint(); syncProject(); syncQueue();
  setInterval(syncQueue, 4000);
  setInterval(syncProject, 2000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { syncQueue(); syncProject(); } });
})();
