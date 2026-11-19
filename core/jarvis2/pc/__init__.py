"""Ressources et contrôle du PC (phase 13, lot J).

- Ressources (CPU, RAM, GPU, VRAM) et modèles Ollama chargés : lecture libre (🟢).
- Ollama à la demande (`ollama.py`), mode jeu = veille stricte (`jeu.py`).
- Contrôle du PC par des actions du registre, donc par la file d'approbations, le journal d'audit et l'arrêt
  d'urgence : volume, sourdine, luminosité, fenêtres, média en cours, verrouillage (🟡), extinction annulable (🔴),
  modes qui changent vraiment Windows (🟡). Chaque action relit l'état : « vérifiée » ou « non vérifiée ».
- Mode sans écran (`ecran.py`) : le contrôle du PC n'est pas proposé et ses actions sont refusées.

Le pilote (`pilote.PilotePC`) est la seule porte vers Windows ; les tests en passent un faux.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ..db import Base, Connexion, Executant
from ..ecran import MESSAGE_SANS_ECRAN
from ..securite.permissions import Action, ErreurAction, Niveau, Registre
from ..securite.urgence import ArretUrgence
from .jeu import REGLAGES, ModeJeu, Reglage
from .ollama import ErreurOllama, GestionnaireOllama
from .pilote import ActionFenetre, CommandeMedia, ErreurPilote, PilotePC, Verification, verifier
from .ressources import SEUIL_ALERTE, Historique

journal = logging.getLogger("jarvis2.pc")

DELAI_EXTINCTION_MIN = 30
DELAI_EXTINCTION_DEFAUT = 60
DELAI_EXTINCTION_MAX = 3600
COMMANDES_MEDIA: tuple[CommandeMedia, ...] = ("lecture", "pause", "bascule", "suivant", "precedent")
ACTIONS_FENETRE: tuple[ActionFenetre, ...] = ("activer", "minimiser", "restaurer", "fermer")
# Plans d'alimentation « performances » fournis par Windows (Performances optimales, Performances élevées)
PLANS_PERFORMANCES = ("e9a42b02-d5df-448d-aa00-03f14749eb61", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c")
NOM_PERFORMANCES = re.compile(r"perf|élev|elev|high|ultim|optimal", re.IGNORECASE)

MODES: dict[str, dict[str, Any]] = {
    "normal": {
        "titre": "Normal",
        "description": "Remet les réglages de Windows d'avant le dernier mode.",
        "reglages": {},
    },
    "jeu": {
        "titre": "Jeu",
        "description": "Plan d'alimentation Performances, bannières de notification coupées, JARVIS en veille.",
        "reglages": {"plan": "performances", "notifications": False, "veille": "force"},
    },
    "concentration": {
        "titre": "Concentration",
        "description": "Bannières de notification de Windows coupées.",
        "reglages": {"notifications": False},
    },
    "nuit": {
        "titre": "Nuit",
        "description": "Thème sombre, luminosité à 30 %, volume ramené à 30 % au plus.",
        "reglages": {"theme_sombre": True, "luminosite": 30, "volume_max": 30},
    },
}
ETAT_DEFAUT: dict[str, Any] = {"jeu": "automatique", "mode": "normal", "avant": None, "modifies": []}


def _entier(p: dict[str, Any], cle: str, mini: int, maxi: int, defaut: int | None = None) -> int:
    valeur = p.get(cle, defaut)
    try:
        n = int(valeur)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ErreurAction(f"Paramètre « {cle} » : nombre attendu") from exc
    if not mini <= n <= maxi:
        raise ErreurAction(f"Paramètre « {cle} » : entre {mini} et {maxi}")
    return n


def _booleen(p: dict[str, Any], cle: str) -> bool:
    return p.get(cle) in (True, "true", "1", 1, "oui")


def _proche(ecart: int) -> Callable[[Any, Any], bool]:
    return lambda lu, attendu: abs(int(lu) - int(attendu)) <= ecart


@dataclass
class ServicePC:
    pool: Base
    pilote: PilotePC | None  # None : contrôle du PC indisponible sur ce système
    ollama: GestionnaireOllama
    historique: Historique
    jeu: ModeJeu
    urgence: ArretUrgence
    plan_jeu: str | None = None  # [pc] plan_jeu : identifiant du plan d'alimentation du mode jeu
    sans_ecran: Callable[[], bool] = lambda: False
    etat: dict[str, Any] = field(default_factory=lambda: dict(ETAT_DEFAUT))
    extinction_le: float | None = None  # heure (time.time) d'une extinction planifiée par JARVIS

    def __post_init__(self) -> None:
        self.jeu.a_l_entree.append(self._liberer_en_veille)
        self.jeu.actif_detection = lambda: not self.sans_ecran()
        self.urgence.au_declenchement.append(self._sur_urgence)
        precedent = self.ollama.bloque
        self.ollama.bloque = lambda: (
            "Arrêt d'urgence actif : Ollama n'est pas démarré" if self.urgence.actif else precedent()
        )

    # --- État enregistré -----------------------------------------------------------------------------------

    async def charger(self, conn: Executant | None = None) -> None:
        valeur = await (conn or self.pool).fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'pc'")
        brut = valeur if isinstance(valeur, dict) else json.loads(valeur or "{}")
        self.etat = {**ETAT_DEFAUT, **brut}
        reglage = self.etat.get("jeu")
        self.jeu.reglage = cast(Reglage, reglage if reglage in REGLAGES else "automatique")

    async def _enregistrer(self, conn: Executant) -> None:
        self.etat["jeu"] = self.jeu.reglage
        await conn.execute(
            "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'pc'",
            json.dumps(self.etat, ensure_ascii=False),
        )

    # --- Lecture --------------------------------------------------------------------------------------------

    @property
    def controle_possible(self) -> bool:
        return self.pilote is not None and not self.sans_ecran()

    def _pilote(self) -> PilotePC:
        if self.sans_ecran():
            raise ErreurAction(MESSAGE_SANS_ECRAN)
        if self.pilote is None:
            raise ErreurAction("Le contrôle du PC n'est pas disponible sur ce système (Windows seulement)")
        return self.pilote

    async def ressources(self) -> dict[str, Any]:
        actuel = await self.historique.actuel()
        ollama = await self.ollama.etat()
        return {
            "actuel": actuel.en_dict(),
            "alertes": actuel.alertes(),
            "seuil_alerte": SEUIL_ALERTE,
            "courbe": self.historique.courbe(),
            "ollama": ollama,
            "jeu": self.jeu.decrire(),
        }

    async def lire(self, quoi: str, appel: Callable[[], Any]) -> Any:
        try:
            return await asyncio.to_thread(appel)
        except ErreurPilote as exc:
            journal.info("Lecture « %s » impossible : %s", quoi, exc)
            return None

    async def etat_pc(self, fenetres: bool = True) -> dict[str, Any]:
        """Tout ce qui se lit (🟢) : volume, luminosité, média, fenêtres, verrouillage, réglages des modes."""
        p = self._pilote()
        volume, luminosite, media, liste, plan, plans, notif, sombre = await asyncio.gather(
            self.lire("volume", p.lire_volume),
            self.lire("luminosité", p.lire_luminosite),
            self.lire("média", p.media),
            self.lire("fenêtres", p.fenetres) if fenetres else asyncio.sleep(0, None),
            self.lire("plan", p.lire_plan_alimentation),
            self.lire("plans", p.plans_alimentation),
            self.lire("notifications", p.lire_notifications),
            self.lire("thème", p.lire_theme_sombre),
        )
        return {
            "volume": {"niveau": volume.niveau, "muet": volume.muet} if volume else None,
            "luminosite": luminosite,
            "media": media.en_dict() if media else None,
            "fenetres": [f.en_dict() for f in liste] if liste is not None else None,
            "plan_alimentation": {"actif": plan, "nom": (plans or {}).get(plan or "")} if plan else None,
            "notifications": notif,
            "theme_sombre": sombre,
            "mode": self.etat.get("mode", "normal"),
            "modes": [{"id": i, "titre": m["titre"], "description": m["description"]} for i, m in MODES.items()],
            "extinction_dans_s": self._extinction_dans(),
        }

    def _extinction_dans(self) -> int | None:
        if self.extinction_le is None:
            return None
        reste = round(self.extinction_le - time.time())
        if reste < 0:
            self.extinction_le = None
            return None
        return reste

    # --- Veille, urgence ------------------------------------------------------------------------------------

    async def _liberer_en_veille(self, motif: str) -> None:
        """Entrée en veille stricte : modèles déchargés, Ollama de JARVIS arrêté."""
        if await self.ollama.joignable():
            await self.ollama.decharger()
        if self.ollama.lance_par_jarvis:
            await self.ollama.arreter(f"veille ({motif})")

    async def _sur_urgence(self) -> None:
        """Arrêt d'urgence : une extinction planifiée par JARVIS est annulée tout de suite."""
        if self.extinction_le is not None and self.pilote is not None:
            try:
                await asyncio.to_thread(self.pilote.annuler_extinction)
            except ErreurPilote:
                journal.exception("Arrêt d'urgence : annulation de l'extinction impossible")
            self.extinction_le = None

    # --- Exécuteurs ----------------------------------------------------------------------------------------

    def _hors_urgence(self) -> None:
        if self.urgence.actif:
            raise ErreurAction("Arrêt d'urgence actif : aucune commande n'est envoyée au PC")

    async def _faire(self, appel: Callable[[], Any]) -> None:
        try:
            await asyncio.to_thread(appel)
        except ErreurPilote as exc:
            raise ErreurAction(str(exc)) from exc

    async def regler_volume(self, niveau: int) -> Verification:
        p = self._pilote()
        await self._faire(lambda: p.regler_volume(niveau))
        return await verifier(lambda: v.niveau if (v := p.lire_volume()) else None, niveau, _proche(1))

    async def regler_muet(self, muet: bool) -> Verification:
        p = self._pilote()
        await self._faire(lambda: p.regler_muet(muet))
        return await verifier(lambda: v.muet if (v := p.lire_volume()) else None, muet)

    async def regler_luminosite(self, niveau: int) -> Verification:
        p = self._pilote()
        await self._faire(lambda: p.regler_luminosite(niveau))
        return await verifier(p.lire_luminosite, niveau, _proche(2), essais=6, pause=0.4)

    async def agir_fenetre(self, ident: int, action: ActionFenetre) -> Verification:
        p = self._pilote()
        await self._faire(lambda: p.agir_fenetre(ident, action))

        def lire() -> Any:
            fenetre = next((f for f in p.fenetres() if f.id == ident), None)
            if action == "fermer":
                return fenetre is None
            if fenetre is None:
                return None
            return {"activer": fenetre.active, "minimiser": fenetre.reduite, "restaurer": not fenetre.reduite}[action]

        v = await verifier(lire, True, essais=8 if action == "fermer" else 4, pause=0.4)
        if not v.verifiee and action == "fermer":
            return Verification(False, True, False, "la fenêtre est encore ouverte (l'application demande peut-être"
                                " d'enregistrer)")  # fmt: skip
        return v

    async def commande_media(self, commande: CommandeMedia) -> Verification:
        p = self._pilote()
        avant = await self.lire("média", p.media)
        await self._faire(lambda: p.commande_media(commande))
        if commande in ("lecture", "pause"):
            return await verifier(lambda: m.statut if (m := p.media()) else None, commande, essais=6, pause=0.4)
        if commande == "bascule":
            attendu = "pause" if avant is not None and avant.statut == "lecture" else "lecture"
            return await verifier(lambda: m.statut if (m := p.media()) else None, attendu, essais=6, pause=0.4)
        titre_avant = avant.titre if avant is not None else None
        return await verifier(
            lambda: m.titre if (m := p.media()) else None,
            "autre titre",
            lambda lu, _: lu != titre_avant,
            essais=8,
            pause=0.5,
        )

    async def verrouiller(self) -> Verification:
        p = self._pilote()
        await self._faire(p.verrouiller)
        return await verifier(p.verrouille, True, essais=8, pause=0.4)

    async def eteindre(self, delai: int) -> dict[str, Any]:
        p = self._pilote()
        await self._faire(lambda: p.planifier_extinction(delai, f"JARVIS : extinction dans {delai} s (annulable)"))
        self.extinction_le = time.time() + delai
        v = Verification(False, f"extinction dans {delai} s", None, "Windows ne permet pas de relire une extinction"
                         " planifiée ; elle reste annulable")  # fmt: skip
        return {"delai_s": delai, "annulable": True, **v.en_dict()}

    async def annuler_extinction(self) -> dict[str, Any]:
        p = self._pilote()
        try:
            annulee = await asyncio.to_thread(p.annuler_extinction)
        except ErreurPilote as exc:
            raise ErreurAction(str(exc)) from exc
        self.extinction_le = None
        if annulee:
            return {"annulee": True, **Verification(True, "annulée", "annulée").en_dict()}
        return {"annulee": False, "verifiee": True, "statut": "vérifiée", "detail": "Aucune extinction n'était prévue"}

    # --- Modes ----------------------------------------------------------------------------------------------

    def _plan_performances(self, plans: dict[str, str]) -> str | None:
        if self.plan_jeu and self.plan_jeu.lower() in plans:
            return self.plan_jeu.lower()
        for guid in PLANS_PERFORMANCES:
            if guid in plans:
                return guid
        return next((g for g, nom in plans.items() if NOM_PERFORMANCES.search(nom)), None)

    async def _photo(self, p: PilotePC) -> dict[str, Any]:
        """Réglages actuels, gardés à l'entrée dans un mode pour être remis par « Normal »."""
        volume = await self.lire("volume", p.lire_volume)
        return {
            "plan": await self.lire("plan", p.lire_plan_alimentation),
            "notifications": await self.lire("notifications", p.lire_notifications),
            "theme_sombre": await self.lire("thème", p.lire_theme_sombre),
            "luminosite": await self.lire("luminosité", p.lire_luminosite),
            "volume": volume.niveau if volume else None,
            "veille": self.jeu.reglage,
        }

    async def _appliquer(self, p: PilotePC, cle: str, valeur: Any) -> dict[str, Any]:
        """Un réglage d'un mode, vérifié en le relisant."""
        try:
            if cle == "plan":
                await asyncio.to_thread(p.regler_plan_alimentation, valeur)
                v = await verifier(p.lire_plan_alimentation, valeur)
            elif cle == "notifications":
                await asyncio.to_thread(p.regler_notifications, valeur)
                v = await verifier(p.lire_notifications, valeur)
            elif cle == "theme_sombre":
                await asyncio.to_thread(p.regler_theme_sombre, valeur)
                v = await verifier(p.lire_theme_sombre, valeur)
            elif cle == "luminosite":
                await asyncio.to_thread(p.regler_luminosite, valeur)
                v = await verifier(p.lire_luminosite, valeur, _proche(2), essais=6, pause=0.4)
            elif cle == "volume":
                await asyncio.to_thread(p.regler_volume, valeur)
                v = await verifier(lambda: x.niveau if (x := p.lire_volume()) else None, valeur, _proche(1))
            elif cle == "veille":
                await self.jeu.regler(valeur)
                v = Verification(self.jeu.reglage == valeur, valeur, self.jeu.reglage)
            else:
                raise ErreurPilote(f"réglage inconnu : {cle}")
        except ErreurPilote as exc:
            return {"reglage": cle, "verifiee": False, "statut": "non vérifiée", "attendu": valeur,
                    "detail": str(exc)}  # fmt: skip
        return {"reglage": cle, **v.en_dict()}

    async def appliquer_mode(self, conn: Connexion, mode: str) -> dict[str, Any]:
        if mode not in MODES:
            raise ErreurAction(f"Mode inconnu : « {mode} » ({', '.join(MODES)})")
        p = self._pilote()
        etapes: list[dict[str, Any]] = []
        ignores: list[str] = []
        if mode == "normal":
            avant = self.etat.get("avant") or {}
            for cle, valeur in avant.items():
                if valeur is not None and cle in self.etat.get("modifies", []):
                    etapes.append(await self._appliquer(p, cle, valeur))
            self.etat.update(mode="normal", avant=None, modifies=[])
        else:
            if self.etat.get("avant") is None:  # on garde l'état d'origine, même en passant d'un mode à l'autre
                self.etat["avant"] = await self._photo(p)
                self.etat["modifies"] = []
            avant = self.etat["avant"]
            for cle, valeur in MODES[mode]["reglages"].items():
                if cle == "plan":
                    valeur = self._plan_performances(await self.lire("plans", p.plans_alimentation) or {})
                    if valeur is None:
                        ignores.append("aucun plan d'alimentation Performances sur ce PC")
                        continue
                if cle == "volume_max":
                    actuel = avant.get("volume")
                    if actuel is not None and actuel <= valeur:
                        continue
                    cle = "volume"
                if cle == "luminosite" and avant.get("luminosite") is None:
                    ignores.append("luminosité non réglable sur cet écran")
                    continue
                etapes.append(await self._appliquer(p, cle, valeur))
                if cle not in self.etat["modifies"]:
                    self.etat["modifies"].append(cle)
            self.etat["mode"] = mode
        await self._enregistrer(conn)
        verifiee = all(e["verifiee"] for e in etapes)
        return {
            "mode": mode,
            "etapes": etapes,
            "ignores": ignores,
            "verifiee": verifiee,
            "statut": "vérifiée" if verifiee else "non vérifiée",
        }

    async def regler_jeu(self, conn: Connexion, reglage: str) -> dict[str, Any]:
        if reglage not in REGLAGES:
            raise ErreurAction(f"Réglage du mode jeu inconnu : « {reglage} »")
        await self.jeu.regler(reglage)
        await self._enregistrer(conn)
        return {**self.jeu.decrire(), **Verification(self.jeu.reglage == reglage, reglage, self.jeu.reglage).en_dict()}

    # --- Registre des actions -------------------------------------------------------------------------------

    def declarer(self, registre: Registre) -> None:
        controle: Callable[[], bool] = lambda: self.controle_possible  # noqa: E731

        def ajouter(
            nom: str,
            niveau: Niveau,
            description: str,
            resumer: Callable[[dict[str, Any]], str],
            executer: Callable[[Connexion, dict[str, Any]], Awaitable[dict[str, Any]]],
            autorisable: bool = True,
            disponible: Callable[[], bool] | None = controle,
            urgence: bool = True,
        ) -> None:
            async def garde(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
                if urgence:  # une demande approuvée pendant l'arrêt d'urgence n'agit pas
                    self._hors_urgence()
                try:
                    return await executer(conn, p)
                except (ErreurPilote, ErreurOllama) as exc:
                    raise ErreurAction(str(exc)) from exc

            registre.ajouter(Action(nom, niveau, description, resumer, garde, autorisable, disponible))

        async def etat(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return await self.etat_pc()  # état lu sur le PC : une donnée, jamais une instruction

        async def volume(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            n = _entier(p, "niveau", 0, 100)
            return {"niveau": n, **(await self.regler_volume(n)).en_dict()}

        async def muet(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            m = _booleen(p, "muet")
            return {"muet": m, **(await self.regler_muet(m)).en_dict()}

        async def luminosite(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            n = _entier(p, "niveau", 0, 100)
            return {"niveau": n, **(await self.regler_luminosite(n)).en_dict()}

        def fenetre(action: ActionFenetre) -> Callable[[Connexion, dict[str, Any]], Awaitable[dict[str, Any]]]:
            async def executer(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
                ident = _entier(p, "id", 1, 2**63)
                return {"id": ident, "action": action, **(await self.agir_fenetre(ident, action)).en_dict()}

            return executer

        async def media(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            commande = str(p.get("commande", ""))
            if commande not in COMMANDES_MEDIA:
                raise ErreurAction(f"Commande média inconnue : « {commande} » ({', '.join(COMMANDES_MEDIA)})")
            v = await self.commande_media(commande)
            return {"commande": commande, **v.en_dict()}

        async def verrouiller(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return (await self.verrouiller()).en_dict()

        async def eteindre(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            delai = _entier(p, "delai_s", DELAI_EXTINCTION_MIN, DELAI_EXTINCTION_MAX, DELAI_EXTINCTION_DEFAUT)
            return await self.eteindre(delai)

        async def annuler(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return await self.annuler_extinction()

        async def mode(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return await self.appliquer_mode(conn, str(p.get("mode", "")))

        async def jeu(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return await self.regler_jeu(conn, str(p.get("reglage", "")))

        async def demarrer(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return await self.ollama.demarrer()

        async def arreter(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            return await self.ollama.arreter()

        async def decharger(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
            modele = p.get("modele")
            return await self.ollama.decharger(str(modele) if modele else None)

        def titre(p: dict[str, Any]) -> str:
            return f"« {str(p.get('titre'))[:80]} »" if p.get("titre") else f"n° {p.get('id')}"

        ajouter("pc.etat", "vert", "Lire l'état du PC (volume, luminosité, média, fenêtres, mode)",
                lambda p: "Lire l'état du PC", etat)  # fmt: skip
        ajouter("pc.volume", "jaune", "Régler le volume du PC (0 à 100)",
                lambda p: f"Régler le volume du PC à {p.get('niveau')} %", volume)  # fmt: skip
        ajouter("pc.sourdine", "jaune", "Couper ou remettre le son du PC",
                lambda p: "Couper le son du PC" if _booleen(p, "muet") else "Remettre le son du PC", muet)  # fmt: skip
        ajouter("pc.luminosite", "jaune", "Régler la luminosité de l'écran (0 à 100)",
                lambda p: f"Régler la luminosité de l'écran à {p.get('niveau')} %", luminosite)  # fmt: skip

        def resume_fenetre(verbe: str) -> Callable[[dict[str, Any]], str]:
            return lambda p: f"{verbe} la fenêtre {titre(p)}"

        verbes: tuple[tuple[ActionFenetre, str], ...] = (
            ("activer", "Mettre au premier plan"),
            ("minimiser", "Réduire"),
            ("restaurer", "Restaurer"),
        )
        for action, verbe in verbes:  # agir sur une fenêtre = un clic à l'écran : jamais « toujours autorisé »
            ajouter(f"pc.fenetre.{action}", "jaune", f"{verbe} une fenêtre du PC", resume_fenetre(verbe),
                    fenetre(action), autorisable=False)  # fmt: skip
        ajouter("pc.fenetre.fermer", "jaune", "Fermer une fenêtre (l'application peut proposer d'enregistrer)",
                lambda p: f"Fermer la fenêtre {titre(p)}", fenetre("fermer"), autorisable=False)  # fmt: skip
        ajouter("pc.media", "jaune", "Lecture, pause, morceau suivant ou précédent du média en cours",
                lambda p: f"Média en cours : {p.get('commande')}", media)  # fmt: skip
        ajouter("pc.verrouiller", "jaune", "Verrouiller la session Windows",
                lambda p: "Verrouiller le PC", verrouiller)  # fmt: skip
        ajouter("pc.eteindre", "rouge", "Éteindre le PC après un délai (annulable jusqu'au bout)",
                lambda p: f"ÉTEINDRE le PC dans {p.get('delai_s', DELAI_EXTINCTION_DEFAUT)} s (annulable)",
                eteindre)  # fmt: skip
        ajouter("pc.extinction.annuler", "vert", "Annuler une extinction planifiée",
                lambda p: "Annuler l'extinction planifiée du PC", annuler, urgence=False)  # fmt: skip
        ajouter("pc.mode", "jaune", "Passer Windows dans un mode (jeu, concentration, nuit, normal)",
                lambda p: f"Passer le PC en mode « {MODES.get(str(p.get('mode')), {}).get('titre', p.get('mode'))} »"
                + (f" : {MODES[str(p.get('mode'))]['description']}" if str(p.get("mode")) in MODES else ""),
                mode)  # fmt: skip
        ajouter("pc.jeu", "vert", "Mode jeu de JARVIS : automatique, veille forcée ou jamais",
                lambda p: f"Mode jeu de JARVIS : {p.get('reglage')}", jeu, disponible=None)  # fmt: skip
        ajouter("ollama.demarrer", "jaune", "Démarrer Ollama (IA locales) à la demande de l'utilisateur",
                lambda p: "Démarrer Ollama (IA locales sur la carte graphique)", demarrer, autorisable=False,
                disponible=None)  # fmt: skip  # jamais « toujours autorisé » : démarrage toujours explicite
        ajouter("ollama.arreter", "jaune", "Arrêter l'Ollama démarré par JARVIS",
                lambda p: "Arrêter Ollama (démarré par JARVIS)", arreter, disponible=None)  # fmt: skip
        ajouter("ollama.decharger", "vert", "Décharger un modèle Ollama (ou tous) de la mémoire",
                lambda p: f"Décharger {p.get('modele') or 'tous les modèles'} d'Ollama", decharger,
                disponible=None, urgence=False)  # fmt: skip  # libérer la mémoire protège : permis en urgence

    def boucles(self) -> list[Coroutine[Any, Any, None]]:
        """Tâches de fond : mesures (seulement quand la vue est ouverte), Ollama inactif, détection des jeux."""
        return [self.historique.boucle(), self.ollama.boucle(), self.jeu.boucle()]


def construire(
    pool: Base, urgence: ArretUrgence, url_ollama: str, config: dict[str, Any], dossier_donnees: Path | None
) -> ServicePC:
    """Service réel : pilote Windows s'il est disponible, mesures et détection en lecture seule."""
    from . import windows
    from .jeu import DetecteurWindows
    from .ollama import INACTIVITE_DEFAUT
    from .ressources import MesureurSysteme

    jeux = config.get("jeux") or []
    inactivite = config.get("ollama_inactivite_min", INACTIVITE_DEFAUT)
    plan = config.get("plan_jeu")
    disponible = windows.disponible()
    return ServicePC(
        pool,
        windows.PiloteWindows() if disponible else None,
        GestionnaireOllama(
            url_ollama,
            inactivite=int(inactivite) if isinstance(inactivite, int) and inactivite > 0 else INACTIVITE_DEFAUT,
            journal_fichier=dossier_donnees / "journaux" / "ollama.log" if dossier_donnees is not None else None,
        ),
        Historique(MesureurSysteme()),
        ModeJeu(
            DetecteurWindows() if disponible else None,
            tuple(str(j) for j in jeux if isinstance(j, str)),
        ),
        urgence,
        plan_jeu=str(plan) if isinstance(plan, str) else None,
    )
