"""Détecteur d'« exécution inventée » : une réponse qui affirme avoir agi sans qu'aucune action n'ait eu lieu.

Un modèle de langage écrit volontiers « J'ai envoyé l'e-mail » ou « I've deleted the file » alors qu'il n'a rien
fait. Après chaque réponse, on repère ces affirmations d'action accomplie (formes françaises et anglaises
courantes) et on les confronte au journal RÉEL du tour : entrées d'audit écrites pendant la réponse (actions 🟡 🔴
exécutées, outils MCP, ateliers…) et outils réellement exécutés que le moteur déclare.

Une affirmation sans action correspondante est **signalée** (meta du message, événement SSE, entrée d'audit) ; la
réponse n'est jamais modifiée.

Pour éviter les faux positifs :
- seules les phrases à la première personne au passé composé (« j'ai… », « je l'ai… », « je viens de… », « I've… »,
  « I just… ») ou au passif accompli (« a bien été envoyé », « has been successfully sent ») comptent : futur
  (« je vais »), conditionnel (« j'aurais »), négation (« je n'ai pas ») et questions sont écartés ;
- les citations (« … », "…", `code`, blocs de code, lignes « > ») et les hypothèses (« si », « par exemple »,
  « if ») sont ignorées ;
- les verbes qui servent aussi à travailler le texte de la réponse (créer, ajouter, modifier, supprimer…)
  n'entrent en compte qu'avec un objet concret (fichier, rappel, e-mail, dossier…) : « j'ai supprimé la
  répétition » ou « j'ai créé un poème » ne sont pas des actions ;
- la lecture et la recherche (« j'ai cherché », « j'ai lu ») ne sont pas des actions à vérifier.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..db import Executant
from . import audit

ACTION_AUDIT = "dialogue.execution_inventee"
LONGUEUR_EXTRAIT = 160

# --- Verbes d'action ----------------------------------------------------------------------------------------------
# (catégorie, lemme, participe passé FR, infinitif FR, objet obligatoire)
_E = r"(?:é|ée|és|ées)"  # accord du participe en -é

VERBES_FR: tuple[tuple[str, str, str, str, bool], ...] = (
    ("envoi", "envoyer", rf"envoy{_E}", r"envoyer", False),
    ("envoi", "expédier", rf"expédi{_E}", r"expédier", False),
    ("envoi", "transmettre", r"transmise?s?", r"transmettre", False),
    ("envoi", "transférer", rf"transfér{_E}", r"transférer", False),
    ("envoi", "publier", rf"publi{_E}", r"publier", False),
    ("envoi", "poster", rf"post{_E}", r"poster", False),
    ("envoi", "contacter", rf"contact{_E}", r"contacter", False),
    ("envoi", "partager", rf"partag{_E}", r"partager", True),
    ("suppression", "supprimer", rf"supprim{_E}", r"supprimer", True),
    ("suppression", "effacer", rf"effac{_E}", r"effacer", True),
    ("suppression", "retirer", rf"retir{_E}", r"retirer", True),
    ("suppression", "vider", rf"vid{_E}", r"vider", True),
    ("suppression", "désinstaller", rf"désinstall{_E}", r"désinstaller", False),
    ("creation", "créer", rf"cré{_E}", r"créer", True),
    ("creation", "ajouter", rf"ajout{_E}", r"ajouter", True),
    ("creation", "écrire", r"écrite?s?", r"écrire", True),
    ("creation", "générer", rf"génér{_E}", r"générer", True),
    ("creation", "copier", rf"copi{_E}", r"copier", True),
    ("modification", "modifier", rf"modifi{_E}", r"modifier", True),
    ("modification", "mettre à jour", r"mise?s? à jour", r"mettre à jour", True),
    ("modification", "changer", rf"chang{_E}", r"changer", True),
    ("modification", "corriger", rf"corrig{_E}", r"corriger", True),
    ("modification", "renommer", rf"renomm{_E}", r"renommer", True),
    ("modification", "déplacer", rf"déplac{_E}", r"déplacer", True),
    ("modification", "configurer", rf"configur{_E}", r"configurer", False),
    ("modification", "activer", rf"activ{_E}", r"activer", False),
    ("modification", "désactiver", rf"désactiv{_E}", r"désactiver", False),
    ("lancement", "lancer", rf"lanc{_E}", r"lancer", False),
    ("lancement", "relancer", rf"relanc{_E}", r"relancer", False),
    ("lancement", "démarrer", rf"démarr{_E}", r"démarrer", False),
    ("lancement", "redémarrer", rf"redémarr{_E}", r"redémarrer", False),
    ("lancement", "exécuter", rf"exécut{_E}", r"exécuter", False),
    ("lancement", "déclencher", rf"déclench{_E}", r"déclencher", False),
    ("lancement", "arrêter", rf"arrêt{_E}", r"arrêter", True),
    ("enregistrement", "enregistrer", rf"enregistr{_E}", r"enregistrer", True),
    ("enregistrement", "sauvegarder", rf"sauvegard{_E}", r"sauvegarder", True),
    ("enregistrement", "mémoriser", rf"mémoris{_E}", r"mémoriser", True),
    ("installation", "installer", rf"install{_E}", r"installer", False),
    ("installation", "déployer", rf"déploy{_E}", r"déployer", False),
    ("installation", "télécharger", rf"télécharg{_E}", r"télécharger", False),
    ("archivage", "archiver", rf"archiv{_E}", r"archiver", False),
    ("transaction", "payer", rf"pay{_E}", r"payer", False),
    ("transaction", "commander", rf"command{_E}", r"commander", False),
    ("transaction", "réserver", rf"réserv{_E}", r"réserver", False),
    ("transaction", "acheter", rf"achet{_E}", r"acheter", False),
    ("planification", "programmer", rf"programm{_E}", r"programmer", False),
    ("planification", "planifier", rf"planifi{_E}", r"planifier", True),
    ("code", "commiter", rf"commit{_E}", r"commiter", False),
    ("code", "pousser", rf"pouss{_E}", r"pousser", True),
    ("code", "fusionner", rf"fusionn{_E}", r"fusionner", True),
)

# (catégorie, lemme, formes anglaises (passé simple et participe), objet obligatoire)
VERBES_EN: tuple[tuple[str, str, str, bool], ...] = (
    ("envoi", "send", r"sent|emailed|e-mailed|forwarded|texted|messaged", False),
    ("envoi", "publish", r"published|posted", False),
    ("envoi", "share", r"shared", True),
    ("suppression", "delete", r"deleted|erased|wiped|uninstalled", False),
    ("suppression", "remove", r"removed", True),
    ("creation", "create", r"created|added|generated|wrote|written|copied", True),
    ("modification", "update", r"updated|modified|changed|edited|fixed|renamed|moved", True),
    ("modification", "configure", r"configured|enabled|disabled|turned (?:on|off)|switched (?:on|off)", False),
    ("lancement", "run", r"ran|executed|launched|started|restarted|triggered|kicked off", False),
    ("lancement", "stop", r"stopped|killed|shut down", True),
    ("enregistrement", "save", r"saved|stored|recorded", True),
    ("installation", "install", r"installed|deployed|downloaded|uploaded", False),
    ("archivage", "archive", r"archived", False),
    ("transaction", "pay", r"paid|ordered|booked|purchased|bought|reserved", False),
    ("planification", "schedule", r"scheduled|set up a reminder|set a reminder|set an alarm|set a timer", False),
    ("code", "commit", r"committed|pushed|merged", False),
)

# Objets concrets : sans l'un d'eux, un verbe « à objet » décrit le travail sur le texte, pas une action.
OBJETS_FR = (
    r"fichiers?|dossiers?|répertoires?|scripts?|rappels?|alarmes?|minuteurs?|événements?|évènements?|"
    r"rendez-vous|réunions?|agendas?|calendriers?|tâches?|recettes?|chantiers?|ateliers?|missions?|comptes?|"
    r"tickets?|issues?|branches?|commits?|dépôts?|bases? de données|configurations?|config|réglages?|"
    r"paramètres?|contacts?|souvenirs?|mémoire|préférences?|photos?|vidéos?|serveurs?|services?|processus|"
    r"programmes?|applications?|conteneurs?|corbeille|sauvegardes?|liste de courses|lumières?|lampes?|"
    r"pages? web|sites?|disque|playlist|modifications|changements"
)
OBJETS_EN = (
    r"files?|folders?|director(?:y|ies)|scripts?|reminders?|alarms?|timers?|events?|appointments?|meetings?|"
    r"calendar|agenda|tasks?|recipes?|missions?|accounts?|tickets?|issues?|branch(?:es)?|commits?|"
    r"repo(?:sitor(?:y|ies))?|databases?|config(?:uration)?s?|settings?|contacts?|memor(?:y|ies)|preferences?|"
    r"photos?|videos?|servers?|services?|process(?:es)?|programs?|apps?|applications?|containers?|trash|"
    r"backups?|shopping list|lights?|lamps?|web ?pages?|sites?|disk|playlist|changes"
)
# Messages : on en écrit souvent le brouillon dans la réponse (« j'ai modifié le mail ») ; ils ne comptent comme
# objet que pour les verbes qui ne touchent pas au texte (supprimer, archiver, partager).
MESSAGERIE_FR = r"e-?mails?|mails?|courriels?|messages?|sms|textos?|conversations?"
MESSAGERIE_EN = r"e-?mails?|mails?|messages?|sms|texts?|conversations?"
CATEGORIES_MESSAGERIE = frozenset({"envoi", "suppression", "archivage"})
# Catégories qui décrivent souvent le texte même de la réponse (« voici le fichier corrigé ») : écartées quand la
# phrase montre le résultat ou que la réponse contient un bloc de code.
CATEGORIES_TEXTUELLES = frozenset({"creation", "modification"})
_TEXTUEL = re.compile(
    r"ci-dessous|ci-dessus|ci-après|voici|voilà|suivant|suivante|below|above|here is|here's|following"
)

_ADV_FR = (
    r"(?:(?:bien|déjà|aussi|également|donc|alors|ensuite|maintenant|enfin|immédiatement|automatiquement|"
    r"correctement|tout|personnellement|directement|aussitôt|à l'instant|pour vous|avec succès)\s+){0,3}"
)
_ADV_EN = (
    r"(?:(?:just|already|also|now|successfully|then|automatically|finally|directly|quickly|gone ahead and|"
    r"went ahead and|been able to|for you|and)\s+){0,3}"
)
# « j'ai », « je l'ai », « je vous ai », « je vous l'ai », « je les ai », « je lui ai »…
_SUJET_FR = r"(?:\bj'ai|\bje\s+(?:(?:vous|te|lui|leur|me|nous)\s+)?(?:l'|les\s+|la\s+|le\s+)?ai)\s+"
_VIENS_FR = (
    r"\bje\s+(?:vous\s+|te\s+)?viens\s+(?:tout juste\s+|juste\s+)?d(?:'|e\s+)(?:(?:vous|lui|leur|l'|les|la|le)\s*)?"
)
_PASSIF_FR = (
    r"\b(?:a|ont|est|sont)\s+(?:(?:bien|maintenant|désormais|correctement|avec succès)\s+)+(?:été\s+)?"
    r"|\b(?:vient|viennent)\s+d'être\s+"
)
_SUJET_EN = r"\bi(?:'ve|\s+have)?\s+"
_PASSIF_EN = r"\b(?:has|have|was|were|is|are)\s+(?:been\s+)?(?:(?:successfully|now|just|already)\s+)+(?:been\s+)?"

_HYPOTHESES = re.compile(
    r"\b(?:si|s'il|s'ils|supposons|imaginons|admettons|par exemple|if|suppose|imagine|for example|"
    r"for instance|pretend|whether|unless|au cas où|in case)\b"
)
_CITATIONS = (
    re.compile(r"```.*?(?:```|$)", re.S),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"«[^»]*»"),
    re.compile(r"“[^”]*”"),
    re.compile(r'"[^"\n]*"'),
    re.compile(r"^\s*>.*$", re.M),
)
_PHRASES = re.compile(r"[^.!?\n;]+[.!?;]*")


@dataclass(frozen=True, slots=True)
class _Regle:
    categorie: str
    lemme: str
    actif: re.Pattern[str]  # forme active à la première personne
    passif: re.Pattern[str]  # forme passive accomplie


def _regles() -> tuple[_Regle, ...]:
    regles: list[_Regle] = []
    for categorie, lemme, participe, infinitif, objet in VERBES_FR:
        objets = OBJETS_FR + ("|" + MESSAGERIE_FR if categorie in CATEGORIES_MESSAGERIE else "")
        objet_ou_rien = rf"(?=[^.!?;\n]{{0,60}}\b(?:{objets})\b)" if objet else ""
        actif = re.compile(
            rf"(?:{_SUJET_FR}{_ADV_FR}(?:{participe})|{_VIENS_FR}(?:{infinitif}))(?![\w-]){objet_ou_rien}"
        )
        # Passif : l'objet est le sujet (« Le fichier a bien été créé ») et peut précéder le verbe
        passif = re.compile(rf"(?:{_PASSIF_FR})(?:{participe})(?![\w-])")
        regles.append(_Regle(categorie, lemme, actif, passif))
    for categorie, lemme, formes, objet in VERBES_EN:
        objets = OBJETS_EN + ("|" + MESSAGERIE_EN if categorie in CATEGORIES_MESSAGERIE else "")
        objet_ou_rien = rf"(?=[^.!?;\n]{{0,60}}\b(?:{objets})\b)" if objet else ""
        actif = re.compile(rf"{_SUJET_EN}{_ADV_EN}(?:{formes})(?![\w-]){objet_ou_rien}")
        passif = re.compile(rf"(?:{_PASSIF_EN})(?:{formes})(?![\w-])")
        regles.append(_Regle(categorie, lemme, actif, passif))
    return tuple(regles)


_REGLES = _regles()
_OBJET_PHRASE = re.compile(rf"\b(?:{OBJETS_FR}|{OBJETS_EN})\b")
_OBJET_PHRASE_MESSAGERIE = re.compile(rf"\b(?:{OBJETS_FR}|{OBJETS_EN}|{MESSAGERIE_FR}|{MESSAGERIE_EN})\b")
_OBJET_REQUIS = {lemme for _, lemme, _, _, objet in VERBES_FR if objet} | {
    lemme for _, lemme, _, objet in VERBES_EN if objet
}


@dataclass(frozen=True, slots=True)
class Affirmation:
    """Une phrase de la réponse qui affirme une action accomplie."""

    categorie: str  # envoi | suppression | creation | modification | lancement | enregistrement | …
    verbe: str  # lemme : « envoyer », « delete »…
    extrait: str  # la phrase, tronquée

    def en_dict(self) -> dict[str, str]:
        return {"categorie": self.categorie, "verbe": self.verbe, "extrait": self.extrait}


def normaliser(texte: str) -> str:
    """Apostrophes droites, espaces insécables remplacées, formes Unicode composées (la casse est gardée pour
    l'extrait ; les motifs travaillent sur la phrase en minuscules)."""
    return unicodedata.normalize("NFC", texte).replace("’", "'").replace("ʼ", "'").replace("\u00a0", " ")


def sans_citations(texte: str) -> str:
    """Retire ce qui est cité : blocs et extraits de code, guillemets, lignes de citation."""
    for motif in _CITATIONS:
        texte = motif.sub(" ", texte)
    return texte


def affirmations(texte: str) -> list[Affirmation]:
    """Les affirmations d'action accomplie d'une réponse (au plus une par phrase et par catégorie)."""
    trouvees: list[Affirmation] = []
    vues: set[tuple[str, str]] = set()
    normalise = normaliser(texte)
    code = "```" in normalise
    for brute in _PHRASES.findall(sans_citations(normalise)):
        originale = " ".join(brute.split())
        phrase = originale.lower()
        if not phrase or phrase.endswith("?") or _HYPOTHESES.search(phrase):
            continue
        textuelle = code or _TEXTUEL.search(phrase) is not None
        for regle in _REGLES:
            if textuelle and regle.categorie in CATEGORIES_TEXTUELLES:
                continue
            if regle.actif.search(phrase) is None:
                if regle.passif.search(phrase) is None:
                    continue
                objets = _OBJET_PHRASE_MESSAGERIE if regle.categorie in CATEGORIES_MESSAGERIE else _OBJET_PHRASE
                if regle.lemme in _OBJET_REQUIS and objets.search(phrase) is None:
                    continue
            cle = (phrase, regle.categorie)
            if cle in vues:
                continue
            vues.add(cle)
            extrait = originale if len(originale) <= LONGUEUR_EXTRAIT else originale[: LONGUEUR_EXTRAIT - 1] + "…"
            trouvees.append(Affirmation(regle.categorie, regle.lemme, extrait))
    return trouvees


# --- Journal réel du tour -----------------------------------------------------------------------------------------

# Catégories acceptées comme preuve pour chaque catégorie d'affirmation
COMPATIBLES: dict[str, frozenset[str]] = {
    "envoi": frozenset({"envoi"}),
    "suppression": frozenset({"suppression", "archivage"}),  # corbeille plutôt que suppression
    "archivage": frozenset({"archivage", "suppression"}),
    "creation": frozenset({"creation", "enregistrement", "modification"}),
    "modification": frozenset({"modification", "creation", "enregistrement"}),
    "enregistrement": frozenset({"enregistrement", "creation", "modification"}),
    "lancement": frozenset({"lancement"}),
    "installation": frozenset({"installation"}),
    "transaction": frozenset({"transaction"}),
    "planification": frozenset({"planification", "creation"}),
    "code": frozenset({"code", "modification"}),
}
GENERIQUE = "outil"  # outil au sens inconnu (MCP…) : il peut appuyer n'importe quelle affirmation
LECTURE = "lecture"  # lecture, recherche : n'appuie aucune affirmation d'action

_CATEGORIES_ACTION: tuple[tuple[str, re.Pattern[str]], ...] = (
    (LECTURE, re.compile(r"(?:read|lire|lecture|grep|glob|search|cherch|recherch|web_?fetch|consult|list)")),
    ("suppression", re.compile(r"supprim|effac|delete|remove|revoqu|abandonn|vid")),
    ("archivage", re.compile(r"archiv")),
    ("envoi", re.compile(r"envo[iy]|send|mail|publi|post|notif|partag|share")),
    ("installation", re.compile(r"install|telecharg|download|deploy|deploi")),
    ("transaction", re.compile(r"pay|paie|achat|achet|command|order|reserv|book")),
    ("planification", re.compile(r"rappel|remind|planif|schedul|minuteur|timer|alarme")),
    ("code", re.compile(r"commit|fusion|merge|push")),
    ("lancement", re.compile(r"lanc|demarr|execut|start|run|arret|stop|relanc|launch|urgence")),
    ("enregistrement", re.compile(r"enregistr|sauveg|save|memoire|memo|souvenir|noyau")),
    ("creation", re.compile(r"cree|creat|ajout|add|nouveau|new|write|ecri")),
    ("modification", re.compile(r"modif|reglage|renomm|rename|maj|update|activ|consigne|rouvert|edit|config")),
)


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower()) if unicodedata.category(c) != "Mn")


def categorie_action(nom: str, generique: bool = False) -> str | None:
    """Catégorie d'une action réelle d'après son nom (« conversation.supprimer », « mcp.appeler », « Write »…).
    `generique` : une action exécutée au nom inconnu compte comme un outil au sens inconnu."""
    simple = _sans_accents(nom)
    if simple.startswith("mcp."):
        return GENERIQUE  # outil MCP : on ne sait pas ce qu'il fait
    for categorie, motif in _CATEGORIES_ACTION:
        if motif.search(simple):
            return categorie
    return GENERIQUE if generique else None


@dataclass(frozen=True, slots=True)
class ActionReelle:
    nom: str
    categorie: str | None


@dataclass
class JournalTour:
    """Ce qui a réellement été fait pendant un tour : entrées d'audit et outils exécutés par le moteur."""

    actions: list[ActionReelle]

    @classmethod
    def depuis(cls, entrees_audit: Iterable[Mapping[str, Any]], outils: Iterable[str] = ()) -> JournalTour:
        actions: list[ActionReelle] = []
        for e in entrees_audit:
            nom = str(e.get("action", ""))
            resultat = str(e.get("resultat") or "ok")
            if nom == ACTION_AUDIT or nom.startswith("demande.") or resultat.startswith("echec"):
                continue  # un signalement, une demande en attente ou un échec ne sont pas des actions faites
            actions.append(ActionReelle(nom, categorie_action(nom, generique=resultat == "execute")))
        for outil in outils:
            actions.append(ActionReelle(f"outil:{outil}", categorie_action(outil, generique=True)))
        return cls(actions)

    def appuie(self, affirmation: Affirmation) -> bool:
        acceptees = COMPATIBLES.get(affirmation.categorie, frozenset({affirmation.categorie}))
        return any(a.categorie == GENERIQUE or a.categorie in acceptees for a in self.actions)


def inventees(texte: str, journal: JournalTour) -> list[Affirmation]:
    """Les affirmations d'action de `texte` qu'aucune action réelle du tour n'appuie."""
    return [a for a in affirmations(texte) if not journal.appuie(a)]


# --- Lecture de l'audit et signalement ----------------------------------------------------------------------------


async def repere_audit(conn: Executant) -> int:
    """Identifiant de la dernière entrée d'audit : début du tour."""
    dernier = await conn.fetchval("SELECT max(id) FROM audit")
    return int(dernier or 0)


async def journal_depuis(conn: Executant, repere: int, outils: Sequence[str] = ()) -> JournalTour:
    """Journal réel du tour : entrées d'audit écrites après `repere`, plus les outils déclarés par le moteur."""
    lignes = await conn.fetch("SELECT action, resultat FROM audit WHERE id > $1 ORDER BY id", repere)
    return JournalTour.depuis([dict(ligne) for ligne in lignes], outils)


def outils_du_moteur(meta: Mapping[str, Any]) -> list[str]:
    """Outils réellement exécutés que le moteur déclare dans la meta de sa réponse (`outils` : noms)."""
    outils = meta.get("outils")
    if isinstance(outils, list | tuple):
        return [str(o) for o in outils]
    return []


async def signaler(
    conn: Executant,
    trouvees: Sequence[Affirmation],
    *,
    acteur: str,
    cible: str | None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Entrée d'audit 🟡 : catégories et verbes seulement, jamais le texte (il peut être privé)."""
    await audit.journaliser(
        conn,
        acteur=acteur,
        action=ACTION_AUDIT,
        niveau="jaune",
        cible=cible,
        details={
            "nombre": len(trouvees),
            "categories": sorted({a.categorie for a in trouvees}),
            "verbes": sorted({a.verbe for a in trouvees}),
            **(details or {}),
        },
        resultat="signale",
    )
