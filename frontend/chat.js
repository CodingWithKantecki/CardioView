// The chat widget: one button at the bottom right of the stage opens a small box where you ask
// about the data on screen. Questions go to the server (POST /api/chat), which adds the live
// context and asks Gemini; the browser only keeps a short history for follow-up questions.

const MAX_HISTORY = 12;   // six question and answer pairs, the server keeps no more either
const MAX_CHARS = 500;

export function initChat() {
  const root = document.getElementById('chat');
  if (!root) return null;
  const box = root.querySelector('#chat-box');
  const open = root.querySelector('#chat-open');
  const close = root.querySelector('#chat-close');
  const log = root.querySelector('#chat-log');
  const form = root.querySelector('#chat-form');
  const input = root.querySelector('#chat-input');
  const send = form.querySelector('button');
  const history = [];
  let busy = false;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let isOpen = false;
  let closing = 0;   // timer that hides the box if animationend never fires

  function make(role, text) {
    const p = document.createElement('p');
    p.className = `msg ${role}`;
    p.textContent = text;
    return p;
  }

  function add(role, text) {
    const p = make(role, text);
    log.appendChild(p);
    log.scrollTop = log.scrollHeight;
    return p;
  }

  // The box must stay in the DOM while chat-out plays, so closing is a class first and hidden after.
  function hide() {
    clearTimeout(closing);
    closing = 0;
    box.classList.remove('closing');
    box.hidden = true;
  }

  function setOpen(on) {
    isOpen = on;
    open.setAttribute('aria-expanded', String(on));
    if (on) {
      clearTimeout(closing);
      closing = 0;
      box.classList.remove('closing');
      box.hidden = false;
      if (!log.childElementCount) add('model', 'Ask about the heart rate, the ECG, the chamber timing or the signal.');
      input.focus();
    } else if (box.hidden || reduced.matches) {
      hide();
    } else {
      box.classList.add('closing');
      closing = setTimeout(hide, 400);
    }
  }
  box.addEventListener('animationend', (e) => {
    if (e.target === box && box.classList.contains('closing')) hide();
  });

  async function submit(question) {
    busy = true;
    input.disabled = true;
    send.disabled = true;
    add('user', question);
    const pending = add('model pending', 'Thinking');
    let reply = 'Chat failed, try again';
    let ok = false;
    try {
      const r = await fetch('/api/chat', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ question, history: history.slice(-MAX_HISTORY), cid: window.cardioview?.cid }),
      });
      let data = null;
      try { data = await r.json(); } catch { data = null; }
      if (data && typeof data.reply === 'string' && data.reply) reply = data.reply;
      ok = r.ok && data && !data.error;
    } catch {
      reply = 'Server offline, try again';
    }
    const answer = make(ok ? 'model' : 'model error', reply);   // a new node, so the reply rises in too
    pending.replaceWith(answer);
    log.scrollTop = log.scrollHeight;
    if (ok) {   // only real answers become context for the next question
      history.push({ role: 'user', text: question }, { role: 'model', text: reply });
      history.splice(0, Math.max(0, history.length - MAX_HISTORY));
    }
    busy = false;
    input.disabled = false;
    send.disabled = false;
    input.focus();
  }

  open.addEventListener('click', () => setOpen(!isOpen));
  close.addEventListener('click', () => { setOpen(false); open.focus(); });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const q = input.value.trim().slice(0, MAX_CHARS);
    if (!q || busy) return;
    input.value = '';
    submit(q);
  });
  root.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen) { setOpen(false); open.focus(); }
  });
  return { setOpen };
}
