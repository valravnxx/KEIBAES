/* Service worker — v2

   Estrategia: RED PRIMERO, caché de respaldo, para todo lo propio.

   La versión anterior servía el armazón (html/css/js) desde la caché sin
   preguntar a la red, que es más rápido pero tiene un problema práctico:
   al publicar un cambio, el móvil seguía enseñando la versión vieja hasta
   que el navegador decidía renovarla por su cuenta.

   Con esta, cada vez que abres la app con conexión ves lo último. Y sin
   conexión sigue funcionando con lo último que se descargó, que era el
   objetivo. Para una app de este tamaño el coste en velocidad no se nota.

   Si algún día tocas este fichero, sube el número de VERSION: es lo que
   hace que el navegador tire la caché vieja y se quede con la nueva.
*/

var VERSION = 'keiba-es-v2';

var ARMAZON = [
  './', './index.html', './estilos.css', './app.js', './datos.json',
  './manifest.json', './iconos/icono-192.png', './iconos/icono-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(VERSION)
      .then(function (c) { return c.addAll(ARMAZON); })
      .then(function () { return self.skipWaiting(); })
      .catch(function () { return self.skipWaiting(); })
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

  // Lo de fuera (miniaturas de YouTube, tipografías) no se toca:
  // que lo gestione el navegador a su manera.
  if (url.origin !== location.origin) return;

  e.respondWith(
    fetch(req)
      .then(function (r) {
        if (r && r.ok) {
          var copia = r.clone();
          // datos.json se pide con ?v=... para saltarse la caché del
          // navegador; se guarda sin la coletilla para poder recuperarlo.
          var clave = url.pathname.endsWith('datos.json') ? './datos.json' : req;
          caches.open(VERSION).then(function (c) { c.put(clave, copia); });
        }
        return r;
      })
      .catch(function () {
        var clave = url.pathname.endsWith('datos.json') ? './datos.json' : req;
        return caches.match(clave).then(function (hit) {
          return hit || caches.match('./index.html');
        });
      })
  );
});
