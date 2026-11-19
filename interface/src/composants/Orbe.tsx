// Orbe de particules du thème « Présence », en WebGL brut (aucune bibliothèque). Tout le mouvement est calculé dans le
// shader de sommets ; le processeur ne fait que glisser quelques uniformes d'un état à l'autre. Les liens entre voisins
// sont trouvés une fois par grille spatiale (presence.ts). Densité de pixels ≤ 2. Le niveau du micro et les impulsions
// de la voix sont lus dans presence.ts, publiés par le fil audio : le rendu n'attend jamais l'audio.
// Animations réduites : une image fixe, redessinée seulement quand l'état change. Sans WebGL : le noyau SVG habituel.

import { useEffect, useRef, useState } from "react";

import { EVENEMENT_MICRO, type EtatPresence, densitePixels, lireImpulsion, LIBELLES_PRESENCE, microOuvert, type Mouvement, MOUVEMENTS, niveauMicro, rapprocher, rapprocherMouvement, sphereFibonacci, voisinsParGrille } from "../presence";
import { type EtatNoyau, Reacteur } from "./Reacteur";

export type ModeOrbe = "panneau" | "compact" | "fond";

const PARTICULES: Record<ModeOrbe, number> = { panneau: 1600, compact: 320, fond: 3000 };
const TAILLE_POINT: Record<ModeOrbe, number> = { panneau: 3.6, compact: 1.8, fond: 3.8 };
/** Part du plus petit côté occupée par l'orbe. */
const ECHELLE: Record<ModeOrbe, number> = { panneau: 1, compact: 1, fond: 0.62 };
const DEMI_VIE_ETAT = 0.35; // s : passage d'un état à l'autre
const DEMI_VIE_NIVEAU = 0.08; // s : lissage du niveau sonore

const SOMMETS = `
attribute vec3 a_pos;
attribute float a_graine;
uniform float u_t, u_rayon, u_houle, u_anneau, u_niveau, u_rot, u_taille, u_ligne;
uniform vec2 u_echelle;
varying float v_prof;
varying float v_graine;
varying float v_ligne;

float houle(vec3 p, float t) {
  return sin(p.x * 2.1 + t * 1.3) * sin(p.y * 2.7 - t * 0.9) * sin(p.z * 2.3 + t * 1.1)
       + 0.5 * sin(p.x * 3.7 - p.z * 3.1 + t * 1.7)
       + 0.25 * sin(p.y * 5.3 + p.x * 4.1 - t * 2.3);
}

void main() {
  vec3 p = a_pos;
  float h = houle(p * 1.4, u_t + a_graine * 0.6);
  float r = u_rayon * (1.0 + u_houle * h + u_niveau * 0.2 * (0.55 + 0.45 * h));
  vec3 s = p * r;
  // Compactage : la sphère s'aplatit en un anneau serré qui tourne
  vec2 dir = normalize(p.xz + vec2(1e-4));
  float ra = u_rayon * (0.92 + 0.1 * sin(a_graine * 6.2832 + u_t * 2.0));
  s = mix(s, vec3(dir.x * ra, p.y * 0.05 * u_rayon, dir.y * ra), u_anneau);
  float c = cos(u_rot), si = sin(u_rot);
  s = vec3(c * s.x + si * s.z, s.y, -si * s.x + c * s.z);
  float ct = 0.93, st = 0.36; // inclinaison fixe vers l'observateur
  s = vec3(s.x, ct * s.y - st * s.z, st * s.y + ct * s.z);
  float persp = 1.0 / (1.35 - s.z * 0.35);
  v_prof = clamp(0.5 + s.z * 0.6, 0.0, 1.0);
  v_graine = a_graine;
  v_ligne = u_ligne;
  gl_Position = vec4(s.xy * persp * u_echelle, 0.0, 1.0);
  gl_PointSize = u_taille * (0.55 + 0.9 * v_prof) * (0.7 + 0.6 * fract(a_graine * 7.31)) * (1.0 + u_niveau * 0.35) * (1.0 - u_ligne);
}
`;

const FRAGMENTS = `
precision mediump float;
uniform vec3 u_c1, u_c2;
uniform float u_alpha;
varying float v_prof;
varying float v_graine;
varying float v_ligne; // passé par les sommets : un uniforme partagé aurait deux précisions (refus d'édition de liens)

void main() {
  float a = 1.0;
  if (v_ligne < 0.5) {
    float d = length(gl_PointCoord - 0.5);
    a = smoothstep(0.5, 0.12, d);
  }
  vec3 couleur = mix(u_c1, u_c2, smoothstep(0.15, 0.95, v_graine));
  gl_FragColor = vec4(couleur, a * u_alpha * (0.4 + 0.6 * v_prof));
}
`;

type Rvb = [number, number, number];

function lireCouleur(style: CSSStyleDeclaration, nom: string): Rvb {
  const canaux = style.getPropertyValue(nom).trim().split(/\s+/).map(Number);
  const [r = 255, v = 255, b = 255] = canaux.every((x) => Number.isFinite(x)) ? canaux : [];
  return [r / 255, v / 255, b / 255];
}

/** Teintes de l'orbe par état, prises dans les jetons du thème. */
function teintes(etat: EtatPresence, alerte: boolean): [Rvb, Rvb] {
  const s = getComputedStyle(document.documentElement);
  if (alerte) return [lireCouleur(s, "--c-rouge"), lireCouleur(s, "--c-rouge")];
  switch (etat) {
    case "ecoute":
    case "parole":
      return [lireCouleur(s, "--c-cyan-vif"), lireCouleur(s, "--c-cyan")];
    case "reflexion":
      return [lireCouleur(s, "--c-bleu"), lireCouleur(s, "--c-aurore")];
    case "compactage":
      return [lireCouleur(s, "--c-aurore"), lireCouleur(s, "--c-bleu")];
    default:
      return [lireCouleur(s, "--c-cyan"), lireCouleur(s, "--c-aurore")];
  }
}

function rapprocherRvb(de: Rvb, vers: Rvb, dt: number): Rvb {
  return [rapprocher(de[0], vers[0], dt, DEMI_VIE_ETAT), rapprocher(de[1], vers[1], dt, DEMI_VIE_ETAT), rapprocher(de[2], vers[2], dt, DEMI_VIE_ETAT)];
}

function animationsReduites(): boolean {
  return document.documentElement.dataset.animations === "reduites";
}

function noyauDe(etat: EtatPresence, alerte: boolean): EtatNoyau {
  if (alerte) return "alerte";
  if (etat === "reflexion" || etat === "compactage") return "reflexion";
  if (etat === "parole") return "parole";
  return "repos";
}

function compiler(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const sh = gl.createShader(type);
  if (!sh) return null;
  gl.shaderSource(sh, source);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    gl.deleteShader(sh);
    return null;
  }
  return sh;
}

function programme(gl: WebGLRenderingContext): WebGLProgram | null {
  const vs = compiler(gl, gl.VERTEX_SHADER, SOMMETS);
  const fs = compiler(gl, gl.FRAGMENT_SHADER, FRAGMENTS);
  const p = gl.createProgram();
  if (!vs || !fs) return null;
  gl.attachShader(p, vs);
  gl.attachShader(p, fs);
  gl.linkProgram(p);
  return gl.getProgramParameter(p, gl.LINK_STATUS) ? p : null;
}

/** Sommets (x, y, z, graine) des particules, puis des extrémités de chaque lien. */
function geometrie(n: number): { points: Float32Array; liens: Float32Array } {
  const sphere = sphereFibonacci(n);
  const points = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) {
    const graine = Math.abs((Math.sin(i * 12.9898) * 43758.5453) % 1); // pseudo-aléatoire stable
    points.set([sphere[i * 3] ?? 0, sphere[i * 3 + 1] ?? 0, sphere[i * 3 + 2] ?? 0, graine], i * 4);
  }
  const espacement = Math.sqrt((4 * Math.PI) / n);
  const paires = voisinsParGrille(sphere, espacement * 1.3, 2);
  const liens = new Float32Array(paires.length * 4);
  paires.forEach((i, k) => {
    liens.set(points.subarray(i * 4, i * 4 + 4), k * 4);
  });
  return { points, liens };
}

interface Props {
  etat: EtatPresence;
  alerte: boolean;
  mode: ModeOrbe;
}

/** L'orbe seul (toile WebGL) ; repli sur le noyau SVG si WebGL manque ou se perd. */
function ToileOrbe({ etat, alerte, mode }: Props) {
  const toile = useRef<HTMLCanvasElement>(null);
  const cible = useRef({ etat, alerte });
  cible.current = { etat, alerte };
  const redessiner = useRef<(() => void) | null>(null);
  const [sansWebgl, setSansWebgl] = useState(false);

  useEffect(() => {
    const canvas = toile.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: false, powerPreference: "low-power" });
    const prog = gl ? programme(gl) : null;
    if (!gl || !prog) {
      setSansWebgl(true);
      return;
    }
    const { points, liens } = geometrie(PARTICULES[mode]);
    const tampon = (donnees: Float32Array) => {
      const b = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, donnees, gl.STATIC_DRAW);
      return b;
    };
    const bPoints = tampon(points);
    const bLiens = tampon(liens);
    const aPos = gl.getAttribLocation(prog, "a_pos");
    const aGraine = gl.getAttribLocation(prog, "a_graine");
    const u = (nom: string) => gl.getUniformLocation(prog, nom);
    const U = {
      t: u("u_t"), rayon: u("u_rayon"), houle: u("u_houle"), anneau: u("u_anneau"), niveau: u("u_niveau"), rot: u("u_rot"),
      taille: u("u_taille"), ligne: u("u_ligne"), echelle: u("u_echelle"), c1: u("u_c1"), c2: u("u_c2"), alpha: u("u_alpha"),
    };
    gl.useProgram(prog);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE); // additif : les particules qui se croisent s'éclairent
    gl.clearColor(0, 0, 0, 0);

    const lier = (b: WebGLBuffer | null) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 16, 0);
      gl.enableVertexAttribArray(aGraine);
      gl.vertexAttribPointer(aGraine, 1, gl.FLOAT, false, 16, 12);
    };

    let dpr = densitePixels(window.devicePixelRatio);
    const redimensionner = () => {
      dpr = densitePixels(window.devicePixelRatio);
      const l = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== l || canvas.height !== h) {
        canvas.width = l;
        canvas.height = h;
      }
      gl.viewport(0, 0, l, h);
    };

    // Teintes lues dans les jetons seulement quand l'état, l'alerte ou le thème changent (pas à chaque image)
    let cleTeintes = "";
    let vise: [Rvb, Rvb] = [[1, 1, 1], [1, 1, 1]];
    const teintesVisees = (): [Rvb, Rvb] => {
      const { etat: e, alerte: a } = cible.current;
      const cle = `${e}|${String(a)}|${document.documentElement.dataset.theme ?? ""}`;
      if (cle !== cleTeintes) {
        cleTeintes = cle;
        vise = teintes(e, a);
      }
      return vise;
    };
    let mvt: Mouvement = { ...MOUVEMENTS[cible.current.etat] };
    let [c1, c2] = teintesVisees();
    let niveau = 0;
    let rotation = 0;
    let temps = 0;

    const dessiner = () => {
      const l = canvas.width;
      const h = canvas.height;
      const k = ECHELLE[mode];
      gl.uniform2f(U.echelle, (k * Math.min(l, h)) / l, (k * Math.min(l, h)) / h);
      gl.uniform1f(U.t, temps);
      gl.uniform1f(U.rayon, mvt.rayon);
      gl.uniform1f(U.houle, mvt.houle);
      gl.uniform1f(U.anneau, mvt.anneau);
      gl.uniform1f(U.niveau, niveau * mvt.reactivite);
      gl.uniform1f(U.rot, rotation);
      gl.uniform1f(U.taille, TAILLE_POINT[mode] * dpr);
      gl.uniform3f(U.c1, ...c1);
      gl.uniform3f(U.c2, ...c2);
      gl.clear(gl.COLOR_BUFFER_BIT);
      if (liens.length) {
        lier(bLiens);
        gl.uniform1f(U.ligne, 1);
        gl.uniform1f(U.alpha, mvt.liens * 0.6);
        gl.drawArrays(gl.LINES, 0, liens.length / 4);
      }
      lier(bPoints);
      gl.uniform1f(U.ligne, 0);
      gl.uniform1f(U.alpha, 1);
      gl.drawArrays(gl.POINTS, 0, points.length / 4);
    };

    // Image fixe (animations réduites) : l'état est appliqué tel quel, sans temps ni son
    const imageFixe = () => {
      redimensionner();
      mvt = { ...MOUVEMENTS[cible.current.etat] };
      [c1, c2] = teintesVisees();
      niveau = 0;
      temps = 0;
      rotation = 0.6;
      dessiner();
    };

    let visible = true;
    let reduites = animationsReduites();
    let boucle = 0;
    let avant = performance.now();
    const image = (maintenant: number) => {
      boucle = requestAnimationFrame(image);
      const dt = Math.min(0.1, (maintenant - avant) / 1000);
      avant = maintenant;
      if (!visible) return;
      const e = cible.current.etat;
      mvt = rapprocherMouvement(mvt, MOUVEMENTS[e], dt, DEMI_VIE_ETAT);
      const [v1, v2] = teintesVisees();
      c1 = rapprocherRvb(c1, v1, dt);
      c2 = rapprocherRvb(c2, v2, dt);
      const brut = Math.max(niveauMicro(), e === "parole" ? lireImpulsion(dt) * 0.8 : 0);
      niveau = rapprocher(niveau, brut, dt, DEMI_VIE_NIVEAU);
      temps += dt * mvt.vitesse;
      rotation += dt * mvt.rotation * Math.PI * 2;
      dessiner();
    };
    const lancer = () => {
      cancelAnimationFrame(boucle);
      if (reduites) {
        imageFixe();
        return;
      }
      avant = performance.now();
      boucle = requestAnimationFrame(image);
    };
    redessiner.current = () => {
      if (reduites) imageFixe();
    };

    const surTaille = new ResizeObserver(() => {
      redimensionner();
      if (reduites) dessiner();
    });
    surTaille.observe(canvas);
    const surVue = new IntersectionObserver((entrees) => {
      visible = entrees.some((x) => x.isIntersecting);
    });
    surVue.observe(canvas);
    // Réglage « Animations » (lot G) ou préférence du système : html[data-animations] change
    const surAnimations = new MutationObserver(() => {
      const r = animationsReduites();
      if (r === reduites) {
        if (reduites) imageFixe(); // thème changé : nouvelles teintes
        return;
      }
      reduites = r;
      lancer();
    });
    surAnimations.observe(document.documentElement, { attributes: true, attributeFilter: ["data-animations", "data-theme"] });
    const perdu = (ev: Event) => {
      ev.preventDefault();
      setSansWebgl(true);
    };
    canvas.addEventListener("webglcontextlost", perdu);

    redimensionner();
    lancer();
    return () => {
      cancelAnimationFrame(boucle);
      surTaille.disconnect();
      surVue.disconnect();
      surAnimations.disconnect();
      canvas.removeEventListener("webglcontextlost", perdu);
      redessiner.current = null;
      gl.deleteBuffer(bPoints);
      gl.deleteBuffer(bLiens);
      gl.deleteProgram(prog);
    };
  }, [mode]);

  useEffect(() => {
    redessiner.current?.();
  }, [etat, alerte]);

  if (sansWebgl) return <Reacteur etat={noyauDe(etat, alerte)} compact={mode === "compact"} />;
  return <canvas ref={toile} className="orbe-toile" aria-hidden="true" />;
}

/** Jauge du niveau du micro : lue dans presence.ts à chaque image (ou toutes les 120 ms si animations réduites). */
export function JaugeMicro({ compacte = false }: { compacte?: boolean }) {
  const [ouvert, setOuvert] = useState(microOuvert);
  const barre = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const suivre = (e: Event) => {
      setOuvert((e as CustomEvent<unknown>).detail === true);
    };
    window.addEventListener(EVENEMENT_MICRO, suivre);
    return () => {
      window.removeEventListener(EVENEMENT_MICRO, suivre);
    };
  }, []);

  useEffect(() => {
    if (!ouvert) return;
    let boucle = 0;
    let minuterie = 0;
    const axe = compacte ? "scaleY" : "scaleX";
    const maj = () => {
      if (barre.current) barre.current.style.transform = `${axe}(${niveauMicro().toFixed(3)})`;
    };
    const image = () => {
      maj();
      boucle = requestAnimationFrame(image);
    };
    if (animationsReduites()) minuterie = window.setInterval(maj, 120);
    else boucle = requestAnimationFrame(image);
    return () => {
      cancelAnimationFrame(boucle);
      window.clearInterval(minuterie);
    };
  }, [ouvert, compacte]);

  if (compacte && !ouvert) return null;
  return (
    <span className="jauge-micro" data-ouvert={ouvert || undefined} data-compacte={compacte || undefined}>
      {!compacte && <span className="jauge-micro-libelle">{ouvert ? "Micro" : "Micro fermé"}</span>}
      <span className="jauge-micro-piste" aria-hidden="true">
        <span ref={barre} className="jauge-micro-barre" />
      </span>
    </span>
  );
}

/** Présence de JARVIS : orbe, libellé de l'état et niveau du micro. En mode « fond », l'orbe est dessiné ailleurs
 *  (couche de fond du HUD) et ce bloc ne garde que le libellé et la jauge. */
export function Presence({ etat, alerte, mode, avecToile = true }: Props & { avecToile?: boolean }) {
  const libelle = alerte ? "Alerte" : LIBELLES_PRESENCE[etat];
  const compact = mode === "compact";
  return (
    <div className="presence" data-mode={mode} data-etat={etat} data-alerte={alerte || undefined}>
      {avecToile && (
        <div className="presence-orbe" role="img" aria-label={`JARVIS : ${libelle}`}>
          <ToileOrbe etat={etat} alerte={alerte} mode={mode} />
        </div>
      )}
      {!compact && (
        <span className="presence-etat" aria-live="polite">
          {libelle}
        </span>
      )}
      <JaugeMicro compacte={compact} />
    </div>
  );
}

/** Orbe en fond d'écran : toute la fenêtre, derrière les panneaux, sans interaction. */
export function OrbeFond({ etat, alerte }: { etat: EtatPresence; alerte: boolean }) {
  return (
    <div className="orbe-fond">
      <ToileOrbe etat={etat} alerte={alerte} mode="fond" />
    </div>
  );
}
