// Only the public landing loads this script. Each navigation gets a fresh ID.
(() => {
  if (navigator.globalPrivacyControl || navigator.doNotTrack === '1') return;
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  const clicks = {};
  let active = !document.hidden && document.hasFocus(), last = performance.now(), activity = last;
  let elapsed = 0, depth = 0, started = false, lastSent = '';
  function sample() {
    const now = performance.now();
    if (active) elapsed += Math.max(0, Math.min(now, activity + 60000) - last);
    last = now;
    if (!document.hidden) depth = Math.max(depth, Math.min(100, Math.round(100 *
      (window.scrollY + window.innerHeight) / Math.max(1,document.documentElement.scrollHeight))));
  }
  function send(leaving = false) {
    sample();
    if (!started && document.hidden) return;
    started = true;
    const body = JSON.stringify({id, lang: document.documentElement.lang, seconds: Math.min(86400,Math.floor(elapsed/1000)), depth, clicks});
    if (body === lastSent && !leaving) return;
    lastSent = body;
    if (leaving && navigator.sendBeacon && navigator.sendBeacon('/api/landing/metrics', new Blob([body], {type:'application/json'}))) return;
    fetch('/api/landing/metrics', {method:'POST',body,headers:{'Content-Type':'application/json'},keepalive:true,credentials:'omit'})
      .then(response => { if (!response.ok && lastSent === body) lastSent=''; })
      .catch(() => { if (lastSent === body) lastSent=''; });
  }
  function interaction() { sample(); activity = last; }
  function state() {
    sample();
    active = !document.hidden && document.hasFocus();
    if (active) activity = last;
    send(!active);
  }
  for (const event of ['pointerdown','keydown','scroll','touchstart']) window.addEventListener(event, interaction, {passive:true});
  document.addEventListener('visibilitychange', state);
  window.addEventListener('focus', state);
  window.addEventListener('blur', state);
  window.addEventListener('pagehide', () => send(true));
  window.addEventListener('pageshow', state);
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-metric]')?.dataset.metric;
    if (control) { interaction(); clicks[control]=Math.min(999,(clicks[control]||0)+1); send(true); }
  }, true);
  send();
  setInterval(() => { if (active) send(); }, 15000);
})();
