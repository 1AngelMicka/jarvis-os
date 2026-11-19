"""Détecteur d'« exécution inventée » : affirmations repérées, faux positifs écartés, vérification contre le
journal réel du tour (audit, outils du moteur), signalement dans le dialogue, les missions et l'audit."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any
from uuid import UUID

import pytest

from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import EvenementDialogue, ServiceDialogue
from jarvis2.moteurs.base import (
    Delta,
    EtatSante,
    Evenement,
    Fin,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
    Usage,
)
from jarvis2.moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from jarvis2.securite import audit
from jarvis2.securite.invente import (
    ACTION_AUDIT,
    Affirmation,
    JournalTour,
    affirmations,
    categorie_action,
    inventees,
    outils_du_moteur,
)


def verbes(texte: str) -> list[str]:
    return [a.verbe for a in affirmations(texte)]


# --- Affirmations repérées ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "verbe"),
    [
        ("J'ai envoyé l'e-mail à Paul.", "envoyer"),
        ("C'est fait : j'ai bien envoyé le message.", "envoyer"),
        ("Je vous l'ai envoyé il y a un instant.", "envoyer"),
        ("Je lui ai transmis votre demande.", "transmettre"),
        ("Je viens d'envoyer le courriel.", "envoyer"),
        ("Je viens de lancer la sauvegarde.", "lancer"),
        ("J'ai supprimé le fichier rapport.pdf.", "supprimer"),
        ("J’ai supprimé les trois e-mails de la corbeille.", "supprimer"),  # apostrophe typographique
        ("J'ai créé le dossier Projets sur le bureau.", "créer"),
        ("J'ai ajouté la réunion à votre agenda pour jeudi.", "ajouter"),
        ("J'ai lancé la commande de compilation.", "lancer"),
        ("J'ai exécuté le script.", "exécuter"),
        ("J'ai redémarré le serveur.", "redémarrer"),
        ("J'ai enregistré votre préférence dans ma mémoire.", "enregistrer"),
        ("J'ai installé Ollama.", "installer"),
        ("J'ai archivé la conversation.", "archiver"),
        ("J'ai réservé une table pour deux.", "réserver"),
        ("J'ai programmé un rappel pour demain 9 h.", "programmer"),
        ("J'ai publié l'article.", "publier"),
        ("J'ai poussé la branche sur le dépôt.", "pousser"),
        ("J'ai déjà téléchargé le modèle.", "télécharger"),
        ("J'ai configuré le connecteur.", "configurer"),
        ("Le mail a bien été envoyé.", "envoyer"),
        ("Le fichier vient d'être supprimé.", "supprimer"),
        ("Votre rappel est maintenant programmé.", "programmer"),
        ("I've sent the email to Paul.", "send"),
        ("I have deleted the old files.", "delete"),
        ("I just ran the tests.", "run"),
        ("I've gone ahead and created the folder.", "create"),
        ("I went ahead and booked the restaurant.", "pay"),
        ("I scheduled the meeting for Monday.", "schedule"),
        ("The message has been successfully sent.", "send"),
        ("Done! I've pushed the changes.", "commit"),
        ("I've saved your settings.", "save"),
    ],
)
def test_affirmation_reperee(texte: str, verbe: str) -> None:
    assert verbe in verbes(texte)


# --- Faux positifs écartés ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texte",
    [
        # Futur, proposition, intention
        "Je vais envoyer l'e-mail dès que vous validez.",
        "Je peux supprimer le fichier si vous le souhaitez.",
        "Voulez-vous que j'envoie le message ?",
        "Je propose de créer un dossier Projets.",
        "J'enverrai le rapport demain.",
        "I will send the email once you confirm.",
        "I'll delete the file after your approval.",
        "I can create the folder for you.",
        "Shall I send it now?",
        # Conditionnel, hypothèse
        "J'aurais envoyé le mail si j'avais eu l'accès.",
        "Si j'ai envoyé le mail par erreur, prévenez-moi.",
        "Par exemple, j'ai supprimé le fichier : c'est ce qu'un assistant pourrait dire.",
        "I would have sent it, but I have no access.",
        "If I deleted the file, you would see it in the trash.",
        # Négation
        "Je n'ai pas envoyé l'e-mail.",
        "Je ne l'ai pas supprimé : il faut votre validation.",
        "Je n'ai rien lancé.",
        "I haven't sent anything.",
        "I did not delete the file.",
        "I never ran that script.",
        # Questions
        "Ai-je bien envoyé le mail ?",
        "J'ai envoyé le mail, c'est bien ça ?",
        # Citations
        "Vous avez écrit « j'ai supprimé le fichier », ce qui n'est pas exact.",
        'Le message disait "I\'ve sent the money" : méfiez-vous.',
        "> J'ai envoyé le colis hier.\n\nCette phrase vient de votre fournisseur.",
        "La commande `git push` publie la branche.",
        "```\n# j'ai supprimé le fichier\nrm fichier.txt\n```",
        # Travail sur le texte de la réponse
        "J'ai créé un poème pour vous.",
        "J'ai supprimé la répétition du deuxième paragraphe.",
        "J'ai ajouté une conclusion plus nette.",
        "J'ai modifié le ton pour qu'il soit plus chaleureux.",
        "J'ai rédigé un e-mail de relance que vous pouvez copier.",
        "J'ai modifié le mail pour le rendre plus court.",
        "Voici le fichier corrigé : j'ai modifié le fichier pour retirer le bogue.",
        "J'ai corrigé le script ci-dessous.",
        "J'ai modifié la fonction :\n```python\ndef f():\n    return 1\n```",
        "I've rewritten the paragraph to be clearer.",
        "I created a short summary below.",
        # Autres personnes, autres temps
        "Vous avez envoyé le mail hier.",
        "Paul a supprimé le fichier.",
        "Ce fichier a été créé en 2019.",
        "You have sent three messages today.",
        # Lecture, recherche, réflexion
        "J'ai cherché dans ma mémoire et je n'ai rien trouvé.",
        "J'ai lu votre message attentivement.",
        "J'ai bien noté votre demande.",
        "J'ai bien enregistré votre demande.",
        "J'ai compris : vous voulez un résumé.",
        "I've read your notes.",
        # Divers
        "J'ai besoin de votre accord pour envoyer le message.",
        "Rien n'a été envoyé.",
        "",
    ],
)
def test_faux_positifs_ecartes(texte: str) -> None:
    assert affirmations(texte) == []


def test_plusieurs_affirmations_et_extrait() -> None:
    texte = "C'est fait. J'ai envoyé l'e-mail à Paul. J'ai aussi supprimé le brouillon du dossier Envois."
    trouvees = affirmations(texte)
    assert [(a.categorie, a.verbe) for a in trouvees] == [("envoi", "envoyer"), ("suppression", "supprimer")]
    assert trouvees[0].extrait == "J'ai envoyé l'e-mail à Paul."
    long = "J'ai envoyé " + "très " * 80 + "longtemps le message."
    assert len(affirmations(long)[0].extrait) == 160 and affirmations(long)[0].extrait.endswith("…")


def test_une_seule_affirmation_par_phrase_et_categorie() -> None:
    assert len(affirmations("J'ai envoyé le mail et j'ai transmis la pièce jointe.")) == 1


# --- Vérification contre le journal réel --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nom", "categorie"),
    [
        ("conversation.supprimer", "suppression"),
        ("conversation.archiver", "archivage"),
        ("memoire.archiver", "archivage"),
        ("mcp.appeler", "outil"),
        ("recette.lancee", "lancement"),
        ("atelier.cree", "creation"),
        ("atelier.fusionner", "code"),
        ("matin.reglages", "modification"),
        ("Write", "creation"),
        ("Read", "lecture"),
        ("WebSearch", "lecture"),
        ("send_email", "envoi"),
        ("inconnu", None),
    ],
)
def test_categorie_action(nom: str, categorie: str | None) -> None:
    assert categorie_action(nom) == categorie


def test_action_executee_au_nom_inconnu_est_generique() -> None:
    assert categorie_action("truc.machin", generique=True) == "outil"


def test_journal_du_tour() -> None:
    texte = "J'ai supprimé la conversation. J'ai envoyé le récapitulatif par e-mail."
    vide = JournalTour.depuis([])
    assert [a.categorie for a in inventees(texte, vide)] == ["suppression", "envoi"]
    # La suppression a vraiment eu lieu : seul l'envoi reste inventé
    reel = JournalTour.depuis([{"action": "conversation.supprimer", "resultat": "execute"}])
    assert [a.verbe for a in inventees(texte, reel)] == ["envoyer"]
    # Un outil MCP au sens inconnu appuie tout
    assert inventees(texte, JournalTour.depuis([{"action": "mcp.appeler", "resultat": "execute"}])) == []
    # Corbeille plutôt que suppression : un archivage appuie « j'ai supprimé »
    archive = JournalTour.depuis([{"action": "conversation.archiver", "resultat": "execute"}])
    assert [a.categorie for a in inventees(texte, archive)] == ["envoi"]


def test_ce_qui_ne_compte_pas_comme_action() -> None:
    texte = "J'ai supprimé la conversation."
    for entree in (
        {"action": "conversation.supprimer", "resultat": "echec : introuvable"},  # échec
        {"action": "demande.creee", "resultat": "ok"},  # simple demande, pas encore approuvée
        {"action": ACTION_AUDIT, "resultat": "signale"},  # un signalement précédent
        {"action": "jumelage.cree", "resultat": "ok"},  # sans rapport
    ):
        assert len(inventees(texte, JournalTour.depuis([entree]))) == 1, entree


def test_outils_declares_par_le_moteur() -> None:
    texte = "J'ai créé le fichier notes.md."
    assert inventees(texte, JournalTour.depuis([], ["Write"])) == []
    assert len(inventees(texte, JournalTour.depuis([], ["Read"]))) == 1  # lire n'est pas créer
    assert outils_du_moteur({"outils": ["Write", "Bash"]}) == ["Write", "Bash"]
    assert outils_du_moteur({"outils_refuses": 2}) == [] and outils_du_moteur({"outils": "x"}) == []


def test_affirmation_en_dict() -> None:
    a = Affirmation("envoi", "envoyer", "j'ai envoyé le mail.")
    assert a.en_dict() == {"categorie": "envoi", "verbe": "envoyer", "extrait": "j'ai envoyé le mail."}


# --- Dans le dialogue et l'API ------------------------------------------------------------------------------------


class Bavard(Moteur):
    """Moteur factice qui répond un texte donné ; `agir` : écrit une vraie action à l'audit pendant la réponse."""

    id = "bavard"
    nom = "Bavard"

    def __init__(self, texte: str, agir: str | None = None, outils: Sequence[str] = (), pool: Base | None = None):
        self.texte, self.agir, self.outils, self.pool = texte, agir, list(outils), pool

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        if self.agir and self.pool is not None:
            await audit.journaliser(self.pool, acteur="test", action=self.agir, resultat="execute")
        yield Delta(self.texte)
        meta: dict[str, Any] = {"source_auth": "none"}
        if self.outils:
            meta["outils"] = self.outils
        yield Fin(Reponse(self.texte, "bavard-1", Usage(1, 1), 0.0, meta))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele("bavard-1", "Bavard 1", True)]

    async def health(self) -> EtatSante:
        return EtatSante(True)


def service_bavard(pool: Base, moteur: Bavard) -> ServiceDialogue:
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, {"bavard": MoteurInstrumente(moteur, EnregistreurBase(pool))}, "bavard")
    service.titre_auto = False
    return service


async def tour(service: ServiceDialogue, message: str = "Envoie le mail à Paul") -> list[EvenementDialogue]:
    return [e async for e in service.repondre(message)]


async def signalements(pool: Base) -> list[dict[str, Any]]:
    return [e for e in await audit.lister(pool, 200) if e["action"] == ACTION_AUDIT]


@pytest.mark.base
async def test_dialogue_signale_une_action_inventee(pool: Base) -> None:
    avant = len(await signalements(pool))
    service = service_bavard(pool, Bavard("C'est fait : j'ai envoyé l'e-mail à Paul."))
    evenements = await tour(service)
    types = [e.type for e in evenements]
    assert types == ["debut", "delta", "fin", "invente"]
    fin, signal = evenements[2].donnees, evenements[3].donnees
    assert fin["texte"] == "C'est fait : j'ai envoyé l'e-mail à Paul."  # la réponse n'est jamais modifiée
    assert fin["invente"] == [
        {"categorie": "envoi", "verbe": "envoyer", "extrait": "C'est fait : j'ai envoyé l'e-mail à Paul."}
    ]
    assert signal == {"message_id": fin["message_id"], "affirmations": fin["invente"]}
    # Gardé dans l'historique
    stocke = await service.depot.messages(UUID(evenements[0].donnees["conversation_id"]))
    assert stocke[-1].meta["invente"] == fin["invente"] and stocke[-1].contenu == fin["texte"]
    # Inscrit à l'audit, sans le texte de la réponse
    entrees = await signalements(pool)
    assert len(entrees) == avant + 1
    entree = entrees[0]
    assert entree["niveau"] == "jaune" and entree["cible"] == str(fin["message_id"])
    assert entree["acteur"] == "moteur:bavard" and entree["resultat"] == "signale"
    details = entree["details"] if isinstance(entree["details"], dict) else json.loads(entree["details"])
    assert details["categories"] == ["envoi"] and details["verbes"] == ["envoyer"] and details["nombre"] == 1
    assert "paul" not in json.dumps(details).lower()


@pytest.mark.base
@pytest.mark.parametrize(
    ("texte", "agir", "outils"),
    [
        ("Je vais envoyer l'e-mail dès votre accord.", None, ()),  # futur
        ("Bonjour ! Comment puis-je vous aider ?", None, ()),  # aucune affirmation
        ("J'ai supprimé la conversation.", "conversation.supprimer", ()),  # action réelle pendant le tour
        ("J'ai créé le fichier notes.md.", None, ("Write",)),  # outil déclaré par le moteur
        ("J'ai lancé l'outil demandé.", "mcp.appeler", ()),  # outil MCP
    ],
)
async def test_dialogue_sans_signalement(pool: Base, texte: str, agir: str | None, outils: Sequence[str]) -> None:
    avant = len(await signalements(pool))
    evenements = await tour(service_bavard(pool, Bavard(texte, agir, outils, pool)))
    assert [e.type for e in evenements] == ["debut", "delta", "fin"]
    assert "invente" not in evenements[2].donnees
    assert len(await signalements(pool)) == avant


@pytest.mark.base
async def test_action_d_un_tour_precedent_ne_compte_pas(pool: Base) -> None:
    await audit.journaliser(pool, acteur="test", action="conversation.supprimer", resultat="execute")
    evenements = await tour(service_bavard(pool, Bavard("J'ai supprimé la conversation.")))
    assert evenements[-1].type == "invente"


@pytest.mark.base
async def test_action_d_une_autre_categorie_ne_compte_pas(pool: Base) -> None:
    moteur = Bavard("J'ai supprimé la conversation et j'ai envoyé le résumé par e-mail.", "conversation.supprimer")
    moteur.pool = pool
    evenements = await tour(service_bavard(pool, moteur))
    assert [a["verbe"] for a in evenements[2].donnees["invente"]] == ["envoyer"]


@pytest.mark.base
async def test_detecteur_jamais_bloquant(pool: Base, monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis2.securite import invente

    async def panne(*_: Any, **__: Any) -> Any:
        raise RuntimeError("audit illisible")

    monkeypatch.setattr(invente, "repere_audit", panne)
    evenements = await tour(service_bavard(pool, Bavard("J'ai envoyé l'e-mail.")))
    assert [e.type for e in evenements] == ["debut", "delta", "fin"]
