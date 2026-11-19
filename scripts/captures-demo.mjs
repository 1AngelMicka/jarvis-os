// Captures brutes du Core de démonstration (appelé par `scripts/demo.py captures`).
// Pilote Edge ou Chrome sans fenêtre par le protocole DevTools (WebSocket natif de Node ≥ 22) : aucune dépendance.
// Usage : node captures-demo.mjs <adresse du Core d'essai> <dossier de sortie> ; accès lu dans JARVIS2_DEMO_ACCES.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [adresse, sortie] = process.argv.slice(2);
const acces = process.env.JARVIS2_DEMO_ACCES;
if (!adresse || !sortie || !acces) {
  console.error("Usage : node captures-demo.mjs <adresse> <dossier> (accès dans JARVIS2_DEMO_ACCES)");
  process.exit(2);
}
if (new URL(adresse).port === "8765") {
  console.error("Port 8765 réservé au Core réel : captures refusées.");
  process.exit(2);
}

const NAVIGATEURS = [
  process.env.JARVIS2_NAVIGATEUR,
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);
const executable = NAVIGATEURS.find((c) => existsSync(c));
if (!executable) {
  console.error("Aucun Edge ni Chrome trouvé (JARVIS2_NAVIGATEUR pour l'indiquer).");
  process.exit(2);
}

const PORT_DEVTOOLS = 9333;
const profil = mkdtempSync(join(tmpdir(), "jarvis2-demo-navigateur-"));
const navigateur = spawn(
  executable,
  [
    "--headless=new",
    `--remote-debugging-port=${PORT_DEVTOOLS}`,
    `--user-data-dir=${profil}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--hide-scrollbars",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--lang=fr-FR",
    "about:blank",
  ],
  { stdio: "ignore" },
);

const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function cible() {
  for (let i = 0; i < 50; i++) {
    try {
      const liste = await (await fetch(`http://127.0.0.1:${PORT_DEVTOOLS}/json/list`)).json();
      const page = liste.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      /* navigateur pas encore prêt */
    }
    await pause(200);
  }
  throw new Error("Le navigateur ne répond pas sur le port DevTools.");
}

const ws = new WebSocket(await cible());
await new Promise((ok, ko) => {
  ws.onopen = ok;
  ws.onerror = ko;
});
let numero = 0;
const attentes = new Map();
const erreurs = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && attentes.has(m.id)) {
    const { ok, ko } = attentes.get(m.id);
    attentes.delete(m.id);
    if (m.error) ko(new Error(m.error.message));
    else ok(m.result);
  } else if (m.method === "Runtime.exceptionThrown") {
    erreurs.push(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text);
  } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
    erreurs.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
  }
};
const cdp = (method, params = {}) =>
  new Promise((ok, ko) => {
    const id = ++numero;
    attentes.set(id, { ok, ko });
    ws.send(JSON.stringify({ id, method, params }));
  });
const evaluer = async (expression) => {
  const r = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result.value;
};

async function taille(largeur, hauteur, mobile = false) {
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: largeur,
    height: hauteur,
    deviceScaleFactor: mobile ? 2 : 1,
    mobile,
  });
  await cdp("Emulation.setTouchEmulationEnabled", { enabled: mobile });
}

async function attendre(condition, delai = 15000) {
  const fin = Date.now() + delai;
  while (Date.now() < fin) {
    if (await evaluer(`Boolean(${condition})`)) return;
    await pause(150);
  }
  throw new Error(`Délai dépassé : ${condition}`);
}

/** Charge l'interface avec ce thème (préférence d'appareil) puis attend la conversation affichée. */
async function charger(theme, hash = "") {
  await evaluer(`localStorage.setItem("jarvis2.theme", ${JSON.stringify(theme)})`);
  await cdp("Page.navigate", { url: `${adresse}/${hash}` });
  await pause(400);
  await attendre(`document.querySelector(".barre-etat-texte")?.textContent === "Core en ligne"`);
}

/** Ouvre une conversation de la liste par son titre. */
async function ouvrirConversation(titre) {
  if (await evaluer(`document.body.innerText.includes("Calendrier proposé")`)) return; // déjà ouverte
  await evaluer(`(() => {
    const el = [...document.querySelectorAll("button, a, [role=button]")]
      .filter((b) => b.textContent.includes(${JSON.stringify(titre)}) && b.offsetParent !== null)
      .sort((a, b) => a.textContent.length - b.textContent.length)[0];
    el?.click();
    return Boolean(el);
  })()`);
  await attendre(`document.body.innerText.includes("Calendrier proposé") || document.body.innerText.includes("En cinq points")`);
}

async function vue(nom) {
  await evaluer(`[...document.querySelectorAll(".barre-nav button")].find((b) => b.textContent.trim() === ${JSON.stringify(nom)})?.click()`);
  await pause(300);
}

async function capturer(nom, attente = 1200) {
  await pause(attente); // entrées des panneaux et orbe
  const { data } = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(sortie, `${nom}.png`), Buffer.from(data, "base64"));
  console.log(`capture ${nom}`);
}

try {
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await taille(1280, 800);
  // Origine du Core : l'accès de la base d'essai et les préférences de démonstration (stockage local du profil jetable)
  await cdp("Page.navigate", { url: `${adresse}/v1/sante` });
  await pause(500);
  await evaluer(`localStorage.setItem("jarvis2.jeton", ${JSON.stringify(acces)}); localStorage.setItem("jarvis2.memoire.vu", new Date().toISOString())`);

  const themes = ["jarvis", "studio", "atelier", "console", "presence"];
  for (const [i, theme] of themes.entries()) {
    await charger(theme);
    await ouvrirConversation("Planifier un potager");
    await capturer(`theme-${theme}`, theme === "presence" ? 2500 : 1200);
    await capturer(`gif-${String(i + 1).padStart(2, "0")}-${theme}`, 100);
  }

  await charger("jarvis");
  await vue("Mémoire");
  await capturer("memoire");
  await capturer("gif-06-memoire", 100);

  await charger("jarvis");
  await vue("Agents");
  await capturer("missions");
  await capturer("gif-07-missions", 100);

  await charger("jarvis", "#reglages/themes");
  await capturer("reglages");
  await capturer("gif-08-reglages", 100);

  await taille(375, 812, true);
  await charger("jarvis");
  await ouvrirConversation("Planifier un potager");
  await capturer("telephone");

  if (erreurs.length) {
    console.log(`Console : ${erreurs.length} erreur(s)`);
    for (const e of erreurs) console.log(`  ${e}`);
  } else {
    console.log("Console : aucune erreur");
  }
} catch (exc) {
  // Diagnostic : l'écran et le texte au moment de l'échec, dans le dossier de sortie (jamais dans docs/images)
  await capturer("echec", 0).catch(() => {});
  const texte = await evaluer("document.body.innerText").catch(() => "");
  writeFileSync(join(sortie, "echec.txt"), String(texte));
  console.error(exc);
  process.exitCode = 1;
} finally {
  ws.close();
  navigateur.kill();
  await pause(500);
  rmSync(profil, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
