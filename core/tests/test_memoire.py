"""Mémoire : fonctions pures de la recherche, recherche hybride en base, noyau, injection dans le dialogue."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime, timedelta

import pytest

from jarvis2 import memoire
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue, SourceMemoire
from jarvis2.memoire import (
    ContexteMemoire,
    Expurgateur,
    Resultat,
    Souvenir,
    decouper_requetes,
    fusionner,
    limiter_noyau,
    lire_noyau,
    orientation,
    rechercher,
    rechercher_multi,
    selectionner,
)
from jarvis2.moteurs.base import Message
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente

from .test_registre_telemetrie import FauxMoteur

MAINTENANT = datetime(2026, 11, 18, tzinfo=UTC)
NOM_EXCLU = "Projet Zéphyr"  # sujet exclu fictif : les vrais vivent dans la configuration locale
EXPURGATEUR = Expurgateur((re.compile(r"projet\s+z[ée]phyr", re.IGNORECASE),))
MODELE = "factice"


class EncodeurFactice:
    """Sac de mots haché et normalisé : déterministe, sans modèle."""

    nom_modele = MODELE
    dimension = 384

    async def encoder(self, texte: str) -> list[float]:
        v = [0.0] * self.dimension
        for mot in re.findall(r"\w+", texte.lower()):
            v[int(hashlib.md5(mot.encode()).hexdigest(), 16) % self.dimension] += 1.0  # noqa: S324
        norme = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norme for x in v]


def souvenir(
    ident: str, contenu: str = "x" * 50, *, source: str | None = None, type_: str = "note", age: int = 100
) -> Souvenir:
    date = MAINTENANT - timedelta(days=age)
    return Souvenir(ident, contenu, type_, (), source, "normal", "utilisateur", None, date, date)


# --- Fonctions pures -------------------------------------------------------------------------------------


def test_decouper_requetes() -> None:
    assert decouper_requetes("Quels sont mes objectifs ? et pourquoi ce projet compte-t-il ?") == [
        "Quels sont mes objectifs ? et pourquoi ce projet compte-t-il ?",
        "Quels sont mes objectifs",
        "pourquoi ce projet compte-t-il",
    ]
    assert decouper_requetes("ok") == ["ok"]


def test_orientation() -> None:
    o = orientation("Qu'as-tu appris sur le motion design ?")
    assert o is not None and o.origines == ("mission",) and o.sujet == "le motion design"
    nouveau = orientation("Quoi de neuf ?")
    assert nouveau is not None and nouveau.origines == () and nouveau.recence == 4.0
    assert orientation("Bonjour JARVIS") is None


def test_expurger_retire_le_sujet_exclu() -> None:
    texte = f"Le projet {NOM_EXCLU} avance. JARVIS tourne sur le PC.\n| {NOM_EXCLU} | ligne |\nAutre ligne."
    assert EXPURGATEUR.texte(texte) == "JARVIS tourne sur le PC.\nAutre ligne."
    assert EXPURGATEUR.souvenir(souvenir("a", f"Note sur le {NOM_EXCLU}.")) is None
    intact = souvenir("b", "Rien à signaler ici, texte ordinaire et assez long pour rester.")
    assert EXPURGATEUR.souvenir(intact) is intact
    noyau = [souvenir("c", f"Ne parle pas du {NOM_EXCLU}. Sois bref et précis, toujours.")]
    bloc = ContexteMemoire(noyau=noyau, expurgateur=EXPURGATEUR).bloc()
    assert NOM_EXCLU not in bloc and "Sois bref" in bloc
    assert Expurgateur().texte(texte) == texte  # sans configuration locale, rien n'est retiré


def test_fusion_et_selection() -> None:
    a, b, c = souvenir("a", type_="fait"), souvenir("b", source="doc"), souvenir("c", source="doc")
    par_requete = [[Resultat(a, 0.9), Resultat(b, 0.5), Resultat(c, 0.1)], [Resultat(c, 0.6), Resultat(b, 0.55)]]
    fusion = fusionner(par_requete, seuil=0.2, maintenant=MAINTENANT)
    # Requête 1 : seuil 0,72 -> seul « a » ; requête 2 : seuil 0,48 -> c puis b. Tour à tour : a, c, puis b
    assert [r.souvenir.id for r in fusion] == ["a", "c", "b"]
    assert fusion[0].score > 0.9  # bonus de type « fait » + récence
    assert [r.souvenir.id for r in selectionner(fusion, limite=10, budget=10_000, max_par_source=1)] == ["a", "c"]
    assert [r.souvenir.id for r in selectionner(fusion, limite=10, budget=60)] == ["a"]


def test_limiter_noyau() -> None:
    noyau = [souvenir("a", "a" * 30), souvenir("b", "b" * 30), souvenir("c", "c" * 30)]
    assert [s.id for s in limiter_noyau(noyau, 70)] == ["a", "b"]
    (tronque,) = limiter_noyau([souvenir("long", "z" * 100)], 10)
    assert tronque.contenu == "z" * 9 + "…"


# --- En base ---------------------------------------------------------------------------------------------


async def inserer(
    pool: Base,
    contenu: str,
    *,
    tags: list[str] | None = None,
    prive: bool = False,
    encodeur: EncodeurFactice | None = None,
) -> str:
    return await memoire.ajouter(
        pool,
        contenu,
        type_="fait",
        tags=tags or [],
        confidentialite="local_uniquement" if prive else "normal",
        origine="utilisateur",
        vecteur=await (encodeur or EncodeurFactice()).encoder(contenu),
        modele=MODELE,
    )


@pytest.mark.base
async def test_souvenirs_depasses_archives_ou_autre_modele_ignores(pool: Base) -> None:
    actuel = await inserer(pool, "Le chat s'appelle Moka")
    ancien = await inserer(pool, "Le chat s'appelle Pixel")
    archive = await inserer(pool, "Le chat aime le saumon")
    autre_modele = await inserer(pool, "Le chat dort sur le canapé")
    await pool.execute(
        "UPDATE memoires SET valid_to = now(), superseded_by = $1 WHERE id = $2", actuel, ancien
    )  # remplacé, jamais effacé
    await pool.execute("UPDATE memoires SET archived = true WHERE id = $1", archive)
    await pool.execute("UPDATE memoires SET embedding_model = 'autre-modele' WHERE id = $1", autre_modele)
    resultats = {r.souvenir.id: r.score for r in await rechercher(pool, EncodeurFactice(), "chat", limite=10)}
    assert actuel in resultats and ancien not in resultats and archive not in resultats
    # Vecteur d'un autre modèle : jamais comparé (cosinus nul), seul le plein texte compte
    assert resultats[autre_modele] < resultats[actuel]
    assert await pool.fetchval("SELECT count(*) FROM memoires") == 4


@pytest.mark.base
async def test_recherche_hybride(pool: Base) -> None:
    jardin = await inserer(pool, "Le jardin potager produit des tomates en été")
    await inserer(pool, "La voiture est au garage pour la vidange")
    secret = await inserer(pool, "Mes tomates préférées sont les cœurs de bœuf du jardin", prive=True)
    enc = EncodeurFactice()
    tous = await rechercher(pool, enc, "tomates du jardin", limite=5)
    assert tous[0].souvenir.id in (jardin, secret) and len(tous) == 3
    externes = await rechercher(pool, enc, "tomates du jardin", limite=5, exclure_local=True)
    assert secret not in [r.souvenir.id for r in externes] and externes[0].souvenir.id == jardin
    multi = await rechercher_multi(pool, enc, "tomates du jardin", exclure_local=True)
    assert [r.souvenir.id for r in multi] == [jardin]  # le garage reste sous le seuil relatif


@pytest.mark.base
async def test_noyau_prive_jamais_vers_externe(pool: Base) -> None:
    await inserer(pool, "Je m'appelle Tony et je vis à Malibu", tags=["noyau"], prive=True)
    await inserer(pool, "JARVIS répond en français et vouvoie", tags=["noyau"])
    externe = await lire_noyau(pool, exclure_local=True)
    local = await lire_noyau(pool, exclure_local=False)
    assert [s.contenu for s in externe] == ["JARVIS répond en français et vouvoie"]
    assert len(local) == 2


class MoteurCapteur(FauxMoteur):
    """Faux moteur qui garde les messages reçus."""

    recus: list[Message]

    async def stream(self, messages, options=None):  # type: ignore[no-untyped-def]
        self.recus = list(messages)
        async for ev in super().stream(messages, options):
            yield ev


@pytest.mark.base
@pytest.mark.parametrize("externe", [True, False])
async def test_dialogue_injecte_noyau_et_souvenirs(pool: Base, externe: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    await inserer(pool, "L'utilisateur boit son café sans sucre", tags=["noyau"])
    prive = await inserer(pool, "Code de la porte du garage : 4512", prive=True)
    visible = await inserer(pool, "Le garage a été repeint en bleu au printemps")
    capteur = MoteurCapteur()
    monkeypatch.setattr(MoteurCapteur, "externe", externe)
    depot = DepotConversations(pool)
    moteurs = {"capteur": MoteurInstrumente(capteur, EnregistreurMemoire())}
    service = ServiceDialogue(depot, moteurs, "capteur", SourceMemoire(pool, EncodeurFactice()))
    evenements = [ev async for ev in service.repondre("Que sais-tu du garage ?")]
    consignes = capteur.recus[0].contenu
    assert capteur.recus[0].role == "systeme"
    assert "Noyau (connaissances de référence, prioritaires) :" in consignes
    assert "café sans sucre" in consignes and "repeint en bleu" in consignes
    assert ("4512" in consignes) is (not externe)
    fin = evenements[-1].donnees
    assert visible in fin["souvenirs"] and (prive in fin["souvenirs"]) is (not externe)
    assert evenements[0].donnees["noyau"] == 1
