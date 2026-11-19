"""Profil guidé : questionnaire par sections, réponses gardées dans `profil_reponses` et versées en mémoire.

Les questions sont GÉNÉRIQUES (aucune donnée propre à un utilisateur) ; les réponses ne vivent que dans la base.
Chaque réponse devient un souvenir d'origine `profil` ; une réponse privée reste `local_uniquement` (jamais vers un
moteur externe). Modifier une réponse ferme l'ancien souvenir (`valid_to = now()`) sans l'effacer : l'historique
reste consultable, seule la réponse en cours est cherchée.

Les réponses importées de JARVIS v1 (identifiants de questions qui ne sont pas les nôtres) sont gardées telles
quelles et comptées à part (« héritées »).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import memoire
from .db import Base, Executant
from .embeddings import Encodeur

LONGUEUR_MAX = 4000
COMMENTAIRE_MAX = 1000


@dataclass(frozen=True)
class Question:
    id: str
    texte: str
    aide: str = ""
    exemple: str = ""


@dataclass(frozen=True)
class Section:
    id: str
    titre: str
    description: str
    questions: tuple[Question, ...]
    prive: bool = False  # réponses privées par défaut (modifiable question par question)

    def en_dict(self) -> dict[str, Any]:
        return {"id": self.id, "titre": self.titre, "description": self.description, "prive": self.prive}


def _s(
    ident: str, titre: str, description: str, questions: Sequence[tuple[str, str, str]], prive: bool = False
) -> Section:
    return Section(
        ident,
        titre,
        description,
        tuple(Question(f"{ident}.{q}", texte, aide) for q, texte, aide in questions),
        prive,
    )


SECTIONS: tuple[Section, ...] = (
    _s(
        "identite",
        "Identité",
        "Qui vous êtes, en quelques mots.",
        [
            ("appel", "Comment voulez-vous que JARVIS vous appelle ?", "Prénom, surnom, tutoiement ou vouvoiement."),
            ("presentation", "Comment vous présenteriez-vous en trois phrases ?", ""),
            ("langues", "Quelles langues parlez-vous, et dans laquelle préférez-vous qu'on vous réponde ?", ""),
            ("cadre", "Dans quel cadre de vie êtes-vous en ce moment ?", "Ville ou campagne, seul ou en famille…"),
        ],
    ),
    _s(
        "objectifs",
        "Objectifs",
        "Ce que vous voulez atteindre.",
        [
            ("annee", "Quels sont vos objectifs pour l'année ?", ""),
            ("cinq_ans", "Où aimeriez-vous en être dans cinq ans ?", ""),
            ("priorite", "Quelle est votre priorité numéro un en ce moment ?", ""),
            ("obstacle", "Qu'est-ce qui vous freine le plus pour y arriver ?", ""),
        ],
    ),
    _s(
        "competences",
        "Compétences",
        "Ce que vous savez faire, et ce que vous voulez apprendre à faire.",
        [
            ("fortes", "Dans quoi êtes-vous vraiment bon ?", ""),
            ("outils", "Quels outils, langages ou logiciels maîtrisez-vous ?", ""),
            ("a_developper", "Quelles compétences voulez-vous développer ?", ""),
            ("niveau", "Sur quels sujets faut-il vous parler en expert, et sur lesquels en débutant ?", ""),
        ],
    ),
    _s(
        "travail",
        "Travail",
        "Votre activité et la façon dont vous l'organisez.",
        [
            ("metier", "Que faites-vous comme travail ou activité principale ?", ""),
            ("journee", "À quoi ressemble une journée de travail type ?", ""),
            ("conditions", "Dans quelles conditions travaillez-vous le mieux ?", "Silence, musique, horaires, lieu…"),
            ("aide", "Sur quelles tâches JARVIS vous ferait-il gagner le plus de temps ?", ""),
        ],
    ),
    _s(
        "pensee",
        "Façon de penser",
        "Comment vous réfléchissez et décidez.",
        [
            ("approche", "Préférez-vous les vues d'ensemble ou les détails d'abord ?", ""),
            ("decider", "Comment prenez-vous une décision importante ?", ""),
            ("contradiction", "Voulez-vous que JARVIS vous contredise quand il n'est pas d'accord ?", ""),
            ("explications", "Quel type d'explication vous parle le plus ?", "Exemples, schémas, analogies, chiffres…"),
        ],
    ),
    _s(
        "passions",
        "Passions",
        "Ce qui vous anime en dehors des obligations.",
        [
            ("loisirs", "Quels sont vos loisirs et passions ?", ""),
            ("sujets", "De quels sujets pourriez-vous parler pendant des heures ?", ""),
            ("oeuvres", "Quels livres, films, musiques ou jeux vous ont marqué ?", ""),
        ],
    ),
    _s(
        "valeurs",
        "Valeurs",
        "Ce qui compte pour vous.",
        [
            ("essentiel", "Quelles sont les trois valeurs qui comptent le plus pour vous ?", ""),
            ("inacceptable", "Qu'est-ce qui vous est inacceptable ?", ""),
            ("fierte", "De quoi êtes-vous fier dans votre façon d'agir ?", ""),
        ],
    ),
    _s(
        "communication",
        "Communication",
        "Comment JARVIS doit vous parler.",
        [
            ("ton", "Quel ton préférez-vous ?", "Direct, chaleureux, formel, avec de l'humour…"),
            ("longueur", "Réponses courtes ou détaillées ?", ""),
            ("agacements", "Qu'est-ce qui vous agace dans une réponse ?", ""),
            ("rappels", "Comment voulez-vous être relancé quand vous oubliez quelque chose ?", ""),
        ],
    ),
    _s(
        "sante",
        "Santé",
        "Ce que JARVIS doit savoir pour vous ménager. Privé par défaut : reste sur vos appareils.",
        [
            (
                "attention",
                "Y a-t-il des points de santé dont JARVIS doit tenir compte ?",
                "Allergies, régime, besoins.",
            ),
            ("sommeil", "Comment dormez-vous, et combien d'heures vous faut-il ?", ""),
            ("activite", "Quelle activité physique pratiquez-vous ou voulez-vous pratiquer ?", ""),
        ],
        prive=True,
    ),
    _s(
        "apprentissage",
        "Apprentissage",
        "Comment vous apprenez le mieux.",
        [
            ("methode", "Comment apprenez-vous le mieux ?", "Lire, pratiquer, regarder, en parler…"),
            ("en_cours", "Qu'êtes-vous en train d'apprendre en ce moment ?", ""),
            ("rythme", "Combien de temps par semaine pouvez-vous consacrer à apprendre ?", ""),
        ],
    ),
    _s(
        "habitudes",
        "Habitudes",
        "Vos routines, bonnes ou à changer.",
        [
            ("routines", "Quelles routines tenez-vous au quotidien ?", ""),
            ("a_prendre", "Quelle habitude aimeriez-vous prendre ?", ""),
            ("a_perdre", "Quelle habitude aimeriez-vous perdre ?", ""),
        ],
    ),
    _s(
        "projets",
        "Projets et décisions",
        "Ce qui est en cours et ce qui attend une décision.",
        [
            ("en_cours", "Quels projets menez-vous en ce moment ?", ""),
            ("decisions", "Quelles décisions avez-vous à prendre prochainement ?", ""),
            ("abandonnes", "Quels projets avez-vous mis de côté, et pourquoi ?", ""),
        ],
    ),
    _s(
        "rythme",
        "Rythme",
        "Votre horloge de la journée et de la semaine.",
        [
            ("matin_soir", "Êtes-vous plutôt du matin ou du soir ?", ""),
            ("horaires", "Quels sont vos horaires habituels ?", "Lever, travail, repas, coucher."),
            ("indisponible", "À quels moments ne voulez-vous pas être dérangé ?", ""),
        ],
    ),
    _s(
        "energie",
        "Énergie",
        "Ce qui vous recharge et ce qui vous épuise.",
        [
            ("recharge", "Qu'est-ce qui vous redonne de l'énergie ?", ""),
            ("epuise", "Qu'est-ce qui vous épuise ?", ""),
            ("signes", "À quels signes voit-on que vous êtes fatigué ou surchargé ?", ""),
        ],
    ),
    _s(
        "argent",
        "Argent",
        "Votre rapport à l'argent et vos objectifs. Privé par défaut : reste sur vos appareils.",
        [
            ("rapport", "Comment décririez-vous votre rapport à l'argent ?", ""),
            ("objectifs", "Avez-vous des objectifs financiers ?", "Épargne, projet, investissement…"),
            ("vigilance", "Sur quelles dépenses JARVIS doit-il vous alerter ?", ""),
        ],
        prive=True,
    ),
    _s(
        "reussites",
        "Réussites",
        "Ce que vous avez accompli.",
        [
            ("fiertes", "De quelles réussites êtes-vous le plus fier ?", ""),
            ("lecons", "Quelle leçon avez-vous tirée d'un échec ?", ""),
            ("celebrer", "Comment aimez-vous célébrer une réussite ?", ""),
        ],
    ),
    _s(
        "limites",
        "Limites",
        "Ce que JARVIS ne doit jamais faire ou aborder. Privé par défaut : reste sur vos appareils.",
        [
            ("jamais", "Qu'est-ce que JARVIS ne doit jamais faire sans vous demander ?", ""),
            ("sujets", "Y a-t-il des sujets que vous ne voulez pas aborder ?", ""),
            ("personnes", "Y a-t-il des personnes dont JARVIS ne doit pas parler ou garder la trace ?", ""),
        ],
        prive=True,
    ),
)

PAR_SECTION = {s.id: s for s in SECTIONS}
PAR_QUESTION = {q.id: (s, q) for s in SECTIONS for q in s.questions}
TOTAL = len(PAR_QUESTION)


class ErreurProfil(ValueError):
    pass


@dataclass
class Reponse:
    question_id: str
    texte: str
    prive: bool
    commentaire: str | None
    souvenir_id: str | None
    cree_le: datetime | None
    maj_le: datetime | None
    brute: Any = field(default=None, repr=False)

    def en_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "texte": self.texte,
            "prive": self.prive,
            "commentaire": self.commentaire,
            "souvenir_id": self.souvenir_id,
            "cree_le": self.cree_le.isoformat() if self.cree_le else None,
            "maj_le": self.maj_le.isoformat() if self.maj_le else None,
        }


def texte_de(valeur: Any) -> tuple[str, bool]:
    """Texte et confidentialité d'une réponse stockée, quel que soit son format (JARVIS 2 ou import v1)."""
    if isinstance(valeur, str):
        try:
            decode = json.loads(valeur)
        except ValueError:
            return valeur, False
        if not isinstance(decode, str):
            return texte_de(decode)
        return decode, False
    if isinstance(valeur, dict):
        prive = bool(valeur.get("prive") or valeur.get("private"))
        for cle in ("texte", "valeur", "value", "reponse", "answer", "text"):
            if cle in valeur and valeur[cle] is not None:
                return texte_de(valeur[cle])[0], prive
        return json.dumps(valeur, ensure_ascii=False), prive
    if isinstance(valeur, list):
        return ", ".join(texte_de(v)[0] for v in valeur), False
    if valeur is None:
        return "", False
    return str(valeur), False


async def lister(base: Executant) -> dict[str, Reponse]:
    lignes = await base.fetch(
        "SELECT p.question_id, p.reponse, p.commentaire, p.souvenir_id, p.cree_le, p.maj_le, m.confidentialite"
        " FROM profil_reponses p LEFT JOIN memoires m ON m.id = p.souvenir_id"
    )
    reponses: dict[str, Reponse] = {}
    for ligne in lignes:
        texte, prive = texte_de(ligne["reponse"])
        reponses[ligne["question_id"]] = Reponse(
            ligne["question_id"],
            texte,
            prive or ligne["confidentialite"] == "local_uniquement",
            ligne["commentaire"],
            str(ligne["souvenir_id"]) if ligne["souvenir_id"] else None,
            ligne["cree_le"],
            ligne["maj_le"],
            ligne["reponse"],
        )
    return reponses


def progression(reponses: dict[str, Reponse]) -> dict[str, Any]:
    """Avancement par section et point de reprise (première question sans réponse, dans l'ordre)."""
    sections = []
    reprise = None
    for s in SECTIONS:
        faites = sum(1 for q in s.questions if q.id in reponses and reponses[q.id].texte.strip())
        sections.append({**s.en_dict(), "total": len(s.questions), "repondues": faites})
        if reprise is None:
            libre = next((q for q in s.questions if q.id not in reponses or not reponses[q.id].texte.strip()), None)
            if libre is not None:
                reprise = {"section": s.id, "question": libre.id}
    repondues = sum(x["repondues"] for x in sections)
    heritees = sum(1 for qid, r in reponses.items() if qid not in PAR_QUESTION and r.texte.strip())
    return {
        "sections": sections,
        "total": TOTAL,
        "repondues": repondues,
        "pourcentage": round(100 * repondues / TOTAL) if TOTAL else 0,
        "reprise": reprise,
        "heritees": heritees,
    }


def contenu_souvenir(section: Section, question: Question, texte: str) -> str:
    return f"Profil — {section.titre} — {question.texte} {texte}"


async def repondre(
    base: Base,
    question_id: str,
    texte: str,
    *,
    prive: bool | None = None,
    commentaire: str | None = None,
    encodeur: Encodeur | None = None,
) -> tuple[Reponse, bool]:
    """Enregistre (ou modifie) une réponse ; renvoie la réponse et `True` si elle a changé.

    Une réponse modifiée ferme l'ancien souvenir sans l'effacer ; une réponse identique ne touche à rien.
    """
    if question_id not in PAR_QUESTION:
        raise ErreurProfil(f"Question inconnue : « {question_id} »")
    section, question = PAR_QUESTION[question_id]
    texte = texte.strip()
    if not texte:
        raise ErreurProfil("Réponse vide : utilisez « retirer » pour effacer une réponse")
    if len(texte) > LONGUEUR_MAX:
        raise ErreurProfil(f"Réponse trop longue : {LONGUEUR_MAX} caractères au plus")
    commentaire = (commentaire or "").strip()[:COMMENTAIRE_MAX] or None
    actuelle = (await lister(base)).get(question_id)
    if prive is None:
        prive = actuelle.prive if actuelle else section.prive
    if actuelle and actuelle.texte == texte and actuelle.prive == prive and actuelle.commentaire == commentaire:
        return actuelle, False
    contenu = contenu_souvenir(section, question, texte)
    vecteur = modele = None
    if encodeur is not None:
        vecteur = await encodeur.encoder(contenu)
        modele = encodeur.nom_modele
    async with base.acquire() as c:
        conn = c
        async with conn.transaction():
            await _fermer(conn, question_id)
            ident = await memoire.ajouter(
                conn,
                contenu,
                type_="fait",
                tags=["profil", f"profil:{section.id}"],
                source=f"profil:{question_id}",
                confidentialite="local_uniquement" if prive else "normal",
                origine="profil",
                vecteur=vecteur,
                modele=modele,
                importance=0.7,
            )
            await conn.execute(
                "INSERT INTO profil_reponses (question_id, reponse, commentaire, souvenir_id) VALUES ($1, $2, $3, $4)"
                " ON CONFLICT (question_id) DO UPDATE SET reponse = excluded.reponse,"
                " commentaire = excluded.commentaire, souvenir_id = excluded.souvenir_id, maj_le = now()",
                question_id,
                {"texte": texte, "prive": prive},
                commentaire,
                ident,
            )
    nouvelle = (await lister(base))[question_id]
    return nouvelle, True


async def _fermer(conn: Executant, question_id: str) -> None:
    """Ferme le souvenir vivant de cette question (lié ou retrouvé par sa source) : gardé, plus cherché."""
    await conn.execute(
        "UPDATE memoires SET valid_to = now(), maj_le = now() WHERE valid_to IS NULL AND (source = $1"
        " OR id = (SELECT souvenir_id FROM profil_reponses WHERE question_id = $2))",
        f"profil:{question_id}",
        question_id,
    )


async def retirer(base: Base, question_id: str) -> bool:
    """Retire une réponse : son souvenir est fermé (gardé dans l'historique), la question redevient libre."""
    async with base.acquire() as c:
        conn = c
        async with conn.transaction():
            existe = await conn.fetchval("SELECT 1 FROM profil_reponses WHERE question_id = $1", question_id)
            if not existe:
                return False
            await _fermer(conn, question_id)
            await conn.execute("DELETE FROM profil_reponses WHERE question_id = $1", question_id)
    return True


async def historique(base: Executant, question_id: str) -> list[dict[str, Any]]:
    """Anciennes réponses (souvenirs fermés compris), de la plus récente à la plus ancienne."""
    lignes = await base.fetch(
        "SELECT id, contenu, confidentialite, valid_from, valid_to FROM memoires"
        " WHERE origine = 'profil' AND source = $1 ORDER BY cree_le DESC",
        f"profil:{question_id}",
    )
    return [
        {
            "souvenir_id": str(x["id"]),
            "contenu": x["contenu"],
            "prive": x["confidentialite"] == "local_uniquement",
            "depuis": x["valid_from"].isoformat() if x["valid_from"] else None,
            "jusqu_a": x["valid_to"].isoformat() if x["valid_to"] else None,
        }
        for x in lignes
    ]
