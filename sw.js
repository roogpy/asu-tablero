/* Service worker: the app shell is cached on install, flight data is
   network-first with a cache fallback, so the last loaded day stays available
   offline. Bump CACHE_VERSION whenever the shell changes. */

var CACHE_VERSION = 'asu-v4';
var SHELL_CACHE = CACHE_VERSION + '-shell';
var DATA_CACHE = CACHE_VERSION + '-data';

var SHELL_FILES = [
  './',
  'index.html',
  'styles.css',
  'app.js',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-maskable-512.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(function (cache) {
      // cache: 'reload' forces the network. Plain addAll may take the files
      // from the browser's HTTP cache, which would install a new version of
      // the worker around the previous version's files.
      return Promise.all(SHELL_FILES.map(function (file) {
        return cache.add(new Request(file, { cache: 'reload' }));
      }));
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.map(function (name) {
        if (name !== SHELL_CACHE && name !== DATA_CACHE) {
          return caches.delete(name);
        }
        return null;
      }));
    }).then(function () {
      return self.clients.claim();
    })
  );
});

function isData(url) {
  return url.pathname.indexOf('/data/') >= 0 || url.pathname.indexOf('/sample/') >= 0;
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') { return; }

  var url = new URL(request.url);
  if (url.origin !== self.location.origin) { return; }

  if (isData(url)) {
    // Network first: a fresh snapshot beats a stale one, but offline still works.
    event.respondWith(
      fetch(request).then(function (response) {
        if (response && response.ok) {
          var copy = response.clone();
          caches.open(DATA_CACHE).then(function (cache) { cache.put(request, copy); });
        }
        return response;
      }).catch(function () {
        return caches.match(request).then(function (cached) {
          return cached || Response.error();
        });
      })
    );
    return;
  }

  // Shell: cache first, refreshed in the background.
  event.respondWith(
    caches.match(request).then(function (cached) {
      var network = fetch(request).then(function (response) {
        if (response && response.ok) {
          var copy = response.clone();
          caches.open(SHELL_CACHE).then(function (cache) { cache.put(request, copy); });
        }
        return response;
      }).catch(function () {
        return cached || caches.match('index.html');
      });
      return cached || network;
    })
  );
});
