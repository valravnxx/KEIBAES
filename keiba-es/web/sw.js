/* Service worker: la app funciona sin conexión con lo último que se descargó.
   Estrategia deliberada y distinta según el recurso:
     · el armazón (html/css/js/iconos) → cache primero, es estable
     · datos.json                      → red primero, cache de respaldo
   Así abres la app en el metro y ves el boletín de ayer en lugar de un error. */

var VERSION = 'keiba-es-v1';
var ARMAZON = [
  './', './index.html', './estilos.css', './app.js', './manifest.json',
  './iconos/icono-192.png', './iconos/icono-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(VERSION)
      .then(function (c) { return c.addAll(ARMAZON); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (ks) {
      return Promise.all(ks.filter(function (k) { return k !== VERSION; })
                          .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;

  var url = new URL(req.url);

  // Nunca cachear lo de fuera (miniaturas de YouTube, anuncios).
  if (url.origin !== location.origin) return;

  if (url.pathname.endsWith('datos.json')) {
    e.respondWith(
      fetch(req).then(function (r) {
        var copia = r.clone();
        caches.open(VERSION).then(function (c) { c.put('./datos.json', copia); });
        return r;
      }).catch(function () {
        return caches.match('./datos.json');
      })
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(function (hit) {
      return hit || fetch(req).then(function (r) {
        if (r.ok) {
          var copia = r.clone();
          caches.open(VERSION).then(function (c) { c.put(req, copia); });
        }
        return r;
      });
    })
  );
});
