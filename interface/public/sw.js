// Service worker de JARVIS : rend l'interface installable (écran d'accueil du téléphone) et rapide à rouvrir.
// - Pages : réseau d'abord (toujours la dernière version), copie de secours si le Core est injoignable.
// - Fichiers compilés (/assets/, noms à empreinte, immuables) et icônes : cache d'abord.
// - API (/v1/) : JAMAIS en cache (données personnelles, jetons) ; le navigateur la traite normalement.
// - Notifications Web Push (lot M) : message chiffré par le Core, court et générique ; un clic ouvre JARVIS sur
//   l'adresse indiquée (toujours une adresse de JARVIS : `/` ou `/#decision=<id>`), jamais un autre site.
// - Liens de fichiers à usage unique (/f/) : jamais en cache.
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
  if (requete.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/v1/") || url.pathname.startsWith("/f/")) return;

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

// --- Notifications Web Push --------------------------------------------------------------------------------
function adresseSure(valeur) {
  // Seulement une adresse de JARVIS lui-même ; le reste ouvre l'accueil
  if (typeof valeur !== "string" || !valeur.startsWith("/") || valeur.startsWith("//")) return "/";
  return /^\/(#decision=[0-9a-f-]{36})?$/i.test(valeur) ? valeur : "/";
}

self.addEventListener("push", (evenement) => {
  let message = {};
  try {
    message = evenement.data ? evenement.data.json() : {};
  } catch {
    message = {};
  }
  const titre = typeof message.titre === "string" ? message.titre.slice(0, 80) : "JARVIS";
  const corps = typeof message.corps === "string" ? message.corps.slice(0, 200) : "";
  const etiquette = typeof message.etiquette === "string" ? message.etiquette.slice(0, 64) : "jarvis";
  evenement.waitUntil(
    self.registration.showNotification(titre, {
      body: corps,
      tag: etiquette,
      renotify: true,
      requireInteraction: etiquette.startsWith("demande-"),
      icon: "/icone-192.png",
      badge: "/icone-192.png",
      lang: "fr",
      data: { url: adresseSure(message.url) },
    }),
  );
});

self.addEventListener("notificationclick", (evenement) => {
  evenement.notification.close();
  const cible = new URL(adresseSure(evenement.notification.data && evenement.notification.data.url), self.location.origin).href;
  evenement.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((fenetres) => {
      for (const f of fenetres) {
        if (new URL(f.url).origin === self.location.origin && "focus" in f) {
          return f.navigate(cible).then((g) => (g ?? f).focus());
        }
      }
      return self.clients.openWindow(cible);
    }),
  );
});
