'use strict';
const $ = id => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
};
const ERR = { room_not_found: 'Комната не найдена. Проверь код.', room_closed: 'Учитель закрыл эту комнату.', bad_code: 'Код — это 6 цифр.',
  bad_name: 'Введи имя.', room_full: 'В комнате нет мест.', rate_limited: 'Слишком часто. Подожди немного.', ai_busy: 'Химолик занят, попробуй через пару секунд.',
  ai_unavailable: 'Химолик сейчас недоступен.', ai_not_configured: 'ИИ не настроен: проверь GEMINI_API_KEY в Render.',
  ai_key_rejected: 'Ключ отклонён или нет доступа к Gemini API. Проверь GEMINI_API_KEY в Render.', unauthorized: 'Нужно войти заново.',
  server_busy: 'Сервер занят, попробуй позже.' };
let catalog = null, token = null, me = null, state = null, items = {}, pollTimer = null, toastT;

function toast(t) { const e = $('toast'); e.textContent = t; e.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => e.hidden = true, 3500); }
function show(id) { document.querySelectorAll('.screen').forEach(s => s.hidden = s.id !== id); }
async function api(path, method = 'GET', body = null, tok = null, retries503 = 0) {
  const h = { 'Content-Type': 'application/json' };
  if (tok) h.Authorization = 'Bearer ' + tok;
  for (let attempt = 0; ; attempt++) {
    try {
      const r = await fetch(path, { method, headers: h, body: body ? JSON.stringify(body) : null });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (r.status === 503 && attempt < retries503) {
          await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
          continue;
        }
        toast(d.message || ERR[d.error] || 'Ошибка. Попробуй ещё раз.'); return null;
      }
      return d;
    } catch (e) { toast('Нет связи с сервером.'); return null; }
  }
}

async function chatApi(path, body, tok = null) {
  const h = { 'Content-Type': 'application/json' };
  if (tok) h.Authorization = 'Bearer ' + tok;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(path, { method: 'POST', headers: h, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (r.ok) return d;
      if (r.status === 503 && attempt < 2) {
        await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
        continue;
      }
      return { __error: d.message || ERR[d.error] || 'Не получилось ответить. Попробуй ещё раз.' };
    } catch (e) {
      return { __error: 'Нет связи с сервером.' };
    }
  }
  return { __error: 'Не получилось ответить. Попробуй ещё раз.' };
}
const name = i => (items[i] ? items[i].name.ru : i);
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

/* ---------- старт ---------- */
async function init() {
  catalog = await api('/api/catalog');
  if (catalog) catalog.items.forEach(i => items[i.id] = i);
  document.querySelectorAll('[data-go]').forEach(b => b.onclick = () => { clearInterval(pollTimer); show('s-' + b.dataset.go); });
  $('b-teacher').onclick = () => { show('s-teacher'); renderItems(); const t = store.get('hm_t'); if (t) loadTeacher(t); };
  $('b-student').onclick = () => show('s-join');
  document.querySelectorAll('input[name=subj]').forEach(r => r.onchange = renderItems);
  $('t-create').onclick = createRoom; $('t-close').onclick = closeRoom; $('j-go').onclick = join;
  const q = new URLSearchParams(location.search).get('room');
  if (q) { $('j-code').value = q.replace(/\D/g, '').slice(0, 6); show('s-join'); $('j-name').focus(); } else show('s-home');
  document.addEventListener('pointermove', moveHands);
  $('b-desk').onclick = goDesk; $('b-reset').onclick = () => act({ action: 'reset' });
  document.querySelectorAll('[data-chat-open]').forEach(b => b.onclick = () => $('chat').hidden = !$('chat').hidden);
  $('chat-x').onclick = () => $('chat').hidden = true;
  $('chat-send').onclick = sendChat; $('chat-q').onkeydown = e => { if (e.key === 'Enter') sendChat(); };
}

/* ---------- педагог ---------- */
function renderItems() {
  const subj = document.querySelector('input[name=subj]:checked').value, box = $('t-items'); box.textContent = '';
  (catalog ? catalog.items : []).filter(i => i.subject === subj).forEach(i => {
    const l = el('label'), c = el('input'); c.type = 'checkbox'; c.value = i.id;
    l.append(c, ' ' + i.formula + ' · ' + i.name.ru); box.append(l);
  });
}
async function createRoom() {
  const picked = [...document.querySelectorAll('#t-items input:checked')].map(c => c.value), title = $('t-title').value.trim();
  if (!title || !picked.length) return toast('Введи название и отметь хотя бы один пункт.');
  const d = await api('/api/rooms', 'POST', { subject: document.querySelector('input[name=subj]:checked').value, title, items: picked });
  if (d) { store.set('hm_t', d.token); showTeacherRoom(d, d.token); }
}
async function loadTeacher(t) { const d = await api('/api/teacher/room', 'GET', null, t); if (d) showTeacherRoom(d, t); else store.set('hm_t', null); }
function showTeacherRoom(d, t) {
  $('t-form').hidden = true; $('t-room').hidden = false;
  $('t-code').textContent = d.code; $('t-url').textContent = d.join_url; $('t-qr').src = '/api/rooms/' + d.code + '/qr.svg';
  clearInterval(pollTimer);
  const poll = async () => {
    const r = await api('/api/teacher/room', 'GET', null, t); if (!r) return clearInterval(pollTimer);
    const ul = $('t-students'); ul.textContent = '';
    if (!r.students.length) ul.append(el('li', '', 'Пока никто не подключился'));
    r.students.forEach(s => {
      const li = el('li'), l = el('span', s.online ? 'on' : 'off', '● ' + s.name);
      li.append(l, el('span', '', s.found + '/' + s.total + ' · вопросов: ' + s.questions + (s.off_topic ? ' ⚠' + s.off_topic : '')));
      ul.append(li);
    });
  };
  poll(); pollTimer = setInterval(poll, 4000);
}
async function closeRoom() {
  if (!confirm('Закрыть комнату?')) return;
  await api('/api/teacher/room', 'DELETE', null, store.get('hm_t')); store.set('hm_t', null); clearInterval(pollTimer);
  $('t-form').hidden = false; $('t-room').hidden = true;
}

/* ---------- ученик ---------- */
async function join() {
  const code = $('j-code').value.trim(), nm = $('j-name').value.trim();
  const body = { code, name: nm || 'Ученик' };
  const old = store.get('hm_s'); if (old) { try { const o = JSON.parse(old); if (o.code === code) { body.token = o.token; body.snapshot = o.snapshot; body.found = o.found; } } catch (e) {} }
  const d = await api('/api/join', 'POST', body); if (!d) return;
  token = d.token; me = d; state = d.state;
  store.set('hm_s', JSON.stringify({ code, token, snapshot: d.snapshot, found: d.found }));
  const rb = $('room-bg'); rb.className = 'bg pan' + (d.room.subject === 'physics' ? ' phys' : '');
  show('s-room');
}
function goDesk() {
  $('room-bg').classList.add('zoom');
  setTimeout(() => { buildLab(); show('s-lab'); }, 800);
}
function buildLab() {
  const phys = me.room.subject === 'physics';
  $('lab-title').textContent = me.room.title; $('flask').hidden = phys; $('phys').hidden = !phys;
  const sh = $('shelf'); sh.textContent = '';
  me.room.items.forEach(id => {
    const it = items[id]; if (!it) return;
    const b = el('button'); b.append(el('b', '', it.formula), el('span', '', it.name.ru));
    b.onclick = () => { pour(); act({ action: 'add', item: id }); }; sh.append(b);
  });
  render(state);
}
async function act(body) {
  const d = await api('/api/act', 'POST', body, token); if (!d) return;
  state = d.state; me.found = d.found; render(state);
  const s = JSON.parse(store.get('hm_s') || '{}'); s.snapshot = d.snapshot; s.found = d.found; store.set('hm_s', JSON.stringify(s));
  (d.events || []).forEach(e => { const ev = catalog.events[e]; if (ev) toast(ev.text.ru + '  (' + d.found.length + '/' + d.total + ')'); });
  ['hand-l', 'hand-r'].forEach(h => { const e = $(h); e.classList.remove('dip'); void e.offsetWidth; e.classList.add('dip'); });
  const f = $('flask'); f.classList.remove('shake'); void f.offsetWidth; f.classList.add('shake');
}
function pour() {
  const s = $('stream'); s.style.setProperty('background', (state && state.liquid) || '#8cc4ff'); s.classList.add('go'); setTimeout(() => s.classList.remove('go'), 600);
}

/* ---------- отрисовка ---------- */
function render(s) {
  if (!s) return;
  if (s.kind === 'chemistry') {
    $('liq').style.height = Math.min(100, s.volume * 28) + '%'; $('liq').style.backgroundColor = s.liquid;
    const sol = s.solids && s.solids[0]; $('ppt').style.height = sol ? Math.min(30, 8 + sol.amount * 30) + '%' : '0%';
    if (sol) $('ppt').style.backgroundColor = sol.color;
    const b = $('bub'); b.textContent = '';
    if (s.gas && s.gas.length) for (let i = 0; i < 10; i++) { const x = el('i'); x.style.left = (15 + Math.random() * 70) + '%'; x.style.animationDelay = (Math.random() * 1.6) + 's'; b.append(x); }
    $('flask').classList.toggle('heat', !!s.heat);
  } else {
    const ammeter = s.elements.find(e => e.id === 'ammeter');
    const voltmeter = s.elements.find(e => e.id === 'voltmeter');
    $('m-a').textContent = ammeter ? ammeter.value.toFixed(2) + ' A' : '— A';
    $('m-v').textContent = voltmeter ? voltmeter.value.toFixed(2) + ' V' : '— V';
    $('meter-a').classList.toggle('active', !!ammeter);
    $('meter-v').classList.toggle('active', !!voltmeter);
    const c = $('circuit'); c.textContent = '';
    s.elements.forEach(e => {
      const bulbStatus = e.id === 'bulb' ? {
        off: ' (не горит)', dim: ' (тускло)', normal: ' (горит)', bright: ' (ярко)', burned: ' (перегорела)'
      }[e.status] : '';
      const chip = el('button', 'chip', name(e.id)
        + (e.id === 'switch' ? (e.on ? ' (вкл)' : ' (выкл)') : '')
        + bulbStatus);
      chip.type = 'button';
      chip.title = e.id === 'switch' ? 'Нажми, чтобы переключить ключ' : 'Нажми, чтобы убрать элемент';
      chip.classList.toggle('lit', e.id === 'bulb' && ['dim', 'normal', 'bright'].includes(e.status));
      chip.classList.toggle('burned', e.id === 'bulb' && e.status === 'burned');
      chip.onclick = () => act(e.id === 'switch' ? { action: 'toggle', index: e.idx } : { action: 'remove', index: e.idx });
      c.append(chip);
    });
    if (s.short) toast('Короткое замыкание! Добавь нагрузку (резистор).');
  }
}
function moveHands(e) {
  const W = innerWidth, H = innerHeight, dx = (e.clientX - W / 2) * 0.12, dy = Math.max(-90, Math.min(20, (e.clientY - H * 0.75) * 0.15));
  $('hand-l').style.transform = `translate(${dx}px,${dy}px) rotate(${dx / 25}deg)`;
  $('hand-r').style.transform = `translate(${dx}px,${dy}px) rotate(${dx / 25}deg)`;
}

/* ---------- чат ---------- */
async function sendChat() {
  const q = $('chat-q').value.trim(); if (!q) return; $('chat-q').value = '';
  const log = $('chat-log'); log.append(el('div', 'msg me', q));
  const wait = el('div', 'msg ai', '…'); log.append(wait); log.scrollTop = log.scrollHeight;
  const teacher = !$('s-teacher').hidden;
  const path = teacher ? '/api/teacher/chat' : '/api/chat';
  const auth = teacher ? store.get('hm_t') : token;
  const d = await chatApi(path, { message: q, lang: 'ru' }, auth);
  wait.textContent = d.__error || d.answer || 'Не получилось ответить. Попробуй ещё раз.';
  log.scrollTop = log.scrollHeight;
}
init();
