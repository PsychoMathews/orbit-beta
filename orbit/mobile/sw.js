// Service worker do Orbit no celular: recebe os avisos (push) e abre o app no toque.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Orbit', {
    body: d.body || '', tag: d.tag || undefined, icon: '/icon-192.png', badge: '/icon-192.png', data: { tab: 'avisos' },
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) { c.postMessage({ goto: 'avisos' }); return c.focus(); }
    return self.clients.openWindow('/#avisos');
  })());
});
