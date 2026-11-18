// Service worker de JARVIS : rend l'interface installable (écran d'accueil du téléphone) et rapide à rouvrir.
// - Pages : réseau d'abord (toujours la dernière version), copie de secours si le Core est injoignable.
// - Fichiers compilés (/assets/, noms à empreinte, immuables) et icônes : cache d'abord.
// - API (/v1/) : JAMAIS en cache (données personnelles, jetons) ; le navigateur la traite normalement.
const CACHE = "jarvis-interface-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (evenement) => {
  evenement.waitUntil(
    caches
      .keys()
      .then((cles) => Promise.all(cles.filter((c) => c !== CACHE).map((c) => caches.delete(c))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (evenement) => {
  const requete = evenement.request;
  const url = new URL(requete.url);
  if (requete.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/v1/")) return;

  if (requete.mode === "navigate") {
    evenement.respondWith(
      fetch(requete)
        .then((reponse) => {
          const copie = reponse.clone();
          if (reponse.ok) void caches.open(CACHE).then((c) => c.put("/", copie));
          return reponse;
        })
        .catch(() => caches.match("/").then((r) => r ?? Response.error())),
    );
    return;
  }

  if (url.pathname.startsWith("/assets/") || /^\/icone[\w-]*\.(png|svg)$/.test(url.pathname)) {
    evenement.respondWith(
      caches.match(requete).then(
        (enCache) =>
          enCache ??
          fetch(requete).then((reponse) => {
            const copie = reponse.clone();
            if (reponse.ok) void caches.open(CACHE).then((c) => c.put(requete, copie));
            return reponse;
          }),
      ),
    );
  }
});
