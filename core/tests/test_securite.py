"""Phase 4 : appareils et jumelage, audit chaîné, approbations 🟡🔴, clés d'accès, arrêt d'urgence, filtre."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base, ErreurBase
from jarvis2.dialogue import TEXTE_MASQUE, ServiceDialogue
from jarvis2.moteurs.base import Delta, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.securite import appareils, audit
from jarvis2.securite.filtre import masquer

from .authentificateur import Authentificateur

pytestmark = pytest.mark.base
ORIGINE = "http://localhost:8765"


class MoteurEspion(Moteur):
    """Garde ce qu'il reçoit ; `lent` : répond un morceau puis attend (pour l'arrêt d'urgence)."""

    id = "espion"
    nom = "Espion"
    externe = True

    def __init__(self, lent: bool = False) -> None:
        self.lent = lent
        self.recus: list[Message] = []
        self.annule = asyncio.Event()

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus = list(messages)
        yield Delta("…")
        if self.lent:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.annule.set()  # ici, le vrai moteur tue la CLI
                raise
        yield Fin(Reponse("ok", "espion-1"))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele("espion-1", "Espion", True)]

    async def health(self) -> EtatSante:
        return EtatSante(True)


class MoteurLocal(MoteurEspion):
    id = "local"
    externe = False


@pytest.fixture
async def systeme(pool: Base) -> dict[str, Any]:
    depot = DepotConversations(pool)
    espion, local, lent = MoteurEspion(), MoteurLocal(), MoteurEspion(lent=True)
    moteurs = {
        "espion": MoteurInstrumente(espion, EnregistreurMemoire()),
        "local": MoteurInstrumente(local, EnregistreurMemoire()),
        "lent": MoteurInstrumente(lent, EnregistreurMemoire()),
    }
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "espion"), "espion")
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    entetes = {"Authorization": f"Bearer {jeton}", "Origin": ORIGINE}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGINE, headers=entetes)
    anonyme = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGINE)
    return {"ctx": ctx, "client": client, "anonyme": anonyme, "espion": espion, "local": local, "lent": lent}


async def nb_audit(pool: Base, action: str) -> int:
    n: int = await pool.fetchval("SELECT count(*) FROM audit WHERE action = $1", action)
    return n


async def creer_conversation(pool: Base) -> str:
    conv = await DepotConversations(pool).creer("À ranger")
    return str(conv.id)


async def demander(client: httpx.AsyncClient, action: str, conversation: str) -> dict[str, Any]:
    rep = await client.post("/v1/actions", json={"action": action, "parametres": {"conversation_id": conversation}})
    resultat: dict[str, Any] = rep.json()
    return resultat


async def enregistrer_cle(client: httpx.AsyncClient) -> Authentificateur:
    cle = Authentificateur()
    options = (await client.post("/v1/cles/enregistrement/options")).json()
    rep = await client.post("/v1/cles/enregistrement", json={"credential": cle.creer(options), "nom": "Hello"})
    assert rep.status_code == 200, rep.text
    return cle


# --- Appareils, jumelage --------------------------------------------------------------------------------


async def test_jeton_obligatoire_et_revocation(systeme: dict[str, Any], pool: Base) -> None:
    client, anonyme = systeme["client"], systeme["anonyme"]
    assert (await anonyme.get("/v1/etat")).status_code == 401
    assert (await anonyme.get("/v1/etat", headers={"Authorization": "Bearer faux"})).status_code == 401
    assert (await anonyme.get("/v1/sante")).status_code == 200  # public
    etat = (await client.get("/v1/etat")).json()
    assert etat["appareil"]["nom"] == "PC" and etat["urgence"]["actif"] is False
    # Le jeton n'est jamais stocké en clair
    assert await pool.fetchval("SELECT count(*) FROM appareils WHERE length(jeton_hash) = 64") == 1
    rep = await client.post(f"/v1/appareils/{etat['appareil']['id']}/revoquer")
    assert rep.json() == {"revoque": True, "soi_meme": True}
    assert (await client.get("/v1/etat")).status_code == 401


async def test_premier_appareil_une_seule_fois_et_depuis_le_pc(
    pool: Base, systeme: dict[str, Any], parametres: Parametres
) -> None:
    anonyme = systeme["anonyme"]
    # Un appareil existe déjà (fixture) : le premier appareil n'est plus possible
    assert (await anonyme.get("/v1/auth/etat")).json() == {"premier_possible": False}
    assert (await anonyme.post("/v1/appareils/premier", json={"nom": "Intrus"})).status_code == 409
    if pool.dialecte == "postgres":
        with pytest.raises(ErreurBase):  # le rôle applicatif ne peut pas effacer un appareil
            await pool.execute("DELETE FROM appareils")
        conn = await asyncpg.connect(parametres.url_base("proprio", "jarvis2_test"))  # installation neuve
        try:
            await conn.execute("TRUNCATE appareils CASCADE")
        finally:
            await conn.close()
    else:  # SQLite : pas de rôles ; installation neuve simulée
        await pool.execute("DELETE FROM appareils")
    distant = await anonyme.post("/v1/appareils/premier", json={"nom": "X"}, headers={"Host": "jarvis.exemple"})
    assert distant.status_code == 403
    assert (await anonyme.get("/v1/auth/etat")).json() == {"premier_possible": True}
    rep = await anonyme.post("/v1/appareils/premier", json={"nom": "Mon PC"})
    assert rep.status_code == 200 and len(rep.json()["jeton"]) >= 40
    assert (await anonyme.post("/v1/appareils/premier", json={"nom": "Second"})).status_code == 409


async def test_jumelage_usage_unique_et_expiration(systeme: dict[str, Any], pool: Base) -> None:
    client, anonyme = systeme["client"], systeme["anonyme"]
    rep = (await client.post("/v1/jumelage", json={"type": "telephone"})).json()
    assert rep["qr"].startswith("data:image/svg+xml") and "#jumeler=" in rep["url"]
    code = rep["url"].split("#jumeler=")[1]
    nouveau = await anonyme.post("/v1/jumelage/echanger", json={"code": code, "nom": "iPhone"})
    assert nouveau.status_code == 200
    jeton = nouveau.json()["jeton"]
    etat = (await anonyme.get("/v1/etat", headers={"Authorization": f"Bearer {jeton}"})).json()
    assert etat["appareil"]["type"] == "telephone"
    rejoue = await anonyme.post("/v1/jumelage/echanger", json={"code": code, "nom": "Intrus"})
    assert rejoue.status_code == 403
    # Code expiré
    rep2 = (await client.post("/v1/jumelage", json={})).json()
    await pool.execute(
        "UPDATE jumelages SET expire_le = $1 WHERE utilise_le IS NULL", datetime.now(UTC) - timedelta(seconds=1)
    )
    code2 = rep2["url"].split("#jumeler=")[1]
    assert (await anonyme.post("/v1/jumelage/echanger", json={"code": code2, "nom": "X"})).status_code == 403
    noms = [a["nom"] for a in (await client.get("/v1/appareils")).json()["appareils"]]
    assert noms == ["PC", "iPhone"]


# --- Audit chaîné ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instruction",
    [
        "UPDATE audit SET resultat = 'falsifie'",
        "DELETE FROM audit",
        "TRUNCATE audit",
        "INSERT INTO audit (acteur, action, niveau, resultat, hash_prec, hash) VALUES ('x','x','vert','x','x','x')",
        "ALTER TABLE audit DISABLE TRIGGER ALL",
    ],
)
async def test_audit_inalterable_par_le_role_applicatif(pool_pg: Base, instruction: str) -> None:
    await pool_pg.fetchval("SELECT id FROM audit_ajouter('test', 'essai', 'vert', NULL, '{}', 'ok')")
    with pytest.raises(ErreurBase):
        await pool_pg.execute(instruction)
    assert await pool_pg.fetchval("SELECT audit_verifier()") is None


@pytest.mark.parametrize("instruction", ["UPDATE audit SET resultat = 'falsifie'", "DELETE FROM audit"])
async def test_audit_sqlite_en_ajout_seul(pool: Base, instruction: str) -> None:
    if pool.dialecte != "sqlite":
        pytest.skip("PostgreSQL : voir test_audit_inalterable_par_le_role_applicatif")
    await audit.journaliser(pool, acteur="test", action="essai", details={"n": 1})
    with pytest.raises(ErreurBase):
        await pool.execute(instruction)
    assert await audit.verifier(pool) is None


async def test_audit_sqlite_falsification_detectee(pool: Base) -> None:
    if pool.dialecte != "sqlite":
        pytest.skip("PostgreSQL : voir test_audit_falsification_detectee")
    for i in range(3):
        await audit.journaliser(pool, acteur="test", action=f"etape{i}", details={"i": i, "clé": "é"})
    cible = await pool.fetchval("SELECT max(id) - 1 FROM audit")
    async with pool.acquire() as conn, conn.transaction():  # qui a le fichier peut retirer le déclencheur…
        await conn.execute("DROP TRIGGER audit_sans_modification")
        await conn.execute("UPDATE audit SET resultat = 'falsifie' WHERE id = $1", cible)
    assert await audit.verifier(pool) == cible  # … mais l'altération est détectée


async def test_audit_texte_canonique_identique_a_postgres(pool_pg: Base) -> None:
    """La chaîne calculée en Python (SQLite) est celle de PostgreSQL : un journal copié se vérifie à l'identique."""
    await audit.journaliser(
        pool_pg, acteur="test", action="canon", cible="x", details={"b": [1, True, None], "aa": 'é"\n', "z": {}}
    )
    ligne = await pool_pg.fetchrow(
        "SELECT id, horodatage, acteur, action, niveau, cible, details, resultat, hash_prec, hash FROM audit"
        " ORDER BY id DESC LIMIT 1"
    )
    assert audit.empreinte(dict(ligne)) == ligne["hash"]


async def test_audit_falsification_detectee(pool_pg: Base, url_proprio: str) -> None:
    pool = pool_pg
    for i in range(3):
        await pool.fetchval("SELECT id FROM audit_ajouter('test', $1, 'vert', NULL, '{}', 'ok')", f"etape{i}")
    cible = await pool.fetchval("SELECT max(id) - 1 FROM audit")
    conn = await asyncpg.connect(url_proprio)  # même le propriétaire (super-utilisateur) : détecté
    try:
        transaction = conn.transaction()
        await transaction.start()
        await conn.execute("ALTER TABLE audit DISABLE TRIGGER audit_sans_modification")
        await conn.execute("UPDATE audit SET resultat = 'falsifie' WHERE id = $1", cible)
        assert await conn.fetchval("SELECT audit_verifier()") == cible
        await transaction.rollback()  # rien ne reste de l'essai
    finally:
        await conn.close()
    assert await pool.fetchval("SELECT audit_verifier()") is None


# --- Approbations et clés d'accès -----------------------------------------------------------------------


async def test_action_jaune_approuvee_d_un_clic(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    conv = await creer_conversation(pool)
    rep = await demander(client, "conversation.archiver", conv)
    assert rep["statut"] == "en_attente" and rep["demande"]["niveau"] == "jaune"
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is False
    assert [d["id"] for d in (await client.get("/v1/etat")).json()["demandes"]] == [rep["demande"]["id"]]
    ok = (await client.post(f"/v1/demandes/{rep['demande']['id']}/approuver", json={})).json()
    assert ok["statut"] == "executee"
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is True
    assert (await client.post(f"/v1/demandes/{rep['demande']['id']}/approuver", json={})).status_code == 409
    assert await nb_audit(pool, "conversation.archiver") >= 1


async def test_action_refusee(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    conv = await creer_conversation(pool)
    rep = await demander(client, "conversation.archiver", conv)
    assert (await client.post(f"/v1/demandes/{rep['demande']['id']}/refuser")).json() == {"statut": "refusee"}
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is False


async def test_action_rouge_exige_une_cle_d_acces(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    conv = await creer_conversation(pool)
    demande = (await demander(client, "conversation.supprimer", conv))["demande"]
    assert demande["niveau"] == "rouge"
    # Un clic ne suffit pas
    refus = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={})
    assert refus.status_code == 409 and "clé d'accès" in refus.json()["detail"]
    # Sans clé enregistrée : le défi est refusé avec une explication
    sans = await client.post(f"/v1/demandes/{demande['id']}/options")
    assert sans.status_code == 409 and "Aucune clé" in sans.json()["detail"]
    # Enregistrement d'une clé d'accès, puis approbation signée
    cle = await enregistrer_cle(client)
    defi = (await client.post(f"/v1/demandes/{demande['id']}/options")).json()
    assert defi["rpId"] == "localhost" and defi["userVerification"] == "required"
    ok = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={"credential": cle.signer(defi)})
    assert ok.status_code == 200 and ok.json()["statut"] == "executee"
    assert await pool.fetchval("SELECT count(*) FROM conversations WHERE id = $1::uuid", conv) == 0
    assert await pool.fetchval("SELECT methode FROM demandes WHERE id = $1::uuid", demande["id"]) == "cle_acces"


async def test_signature_rejouee_ou_detournee_refusee(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    cle = await enregistrer_cle(client)
    d1 = (await demander(client, "conversation.supprimer", await creer_conversation(pool)))["demande"]
    d2 = (await demander(client, "conversation.supprimer", await creer_conversation(pool)))["demande"]
    signee = cle.signer((await client.post(f"/v1/demandes/{d1['id']}/options")).json())
    # Signature d'un défi émis pour la demande 1, présentée pour la demande 2 : refusée
    assert (await client.post(f"/v1/demandes/{d2['id']}/approuver", json={"credential": signee})).status_code == 403
    # Le défi n'a pas été consommé par cet échec ; présenté pour la bonne demande, il passe une fois…
    assert (await client.post(f"/v1/demandes/{d1['id']}/approuver", json={"credential": signee})).status_code == 200
    # … et jamais deux : la demande est traitée et le défi consommé
    assert (await client.post(f"/v1/demandes/{d1['id']}/approuver", json={"credential": signee})).status_code == 403
    # Une autre clé qui se fait passer pour la clé enregistrée est refusée
    faux = Authentificateur()
    faux.id = cle.id
    defi = (await client.post(f"/v1/demandes/{d2['id']}/options")).json()
    assert (
        await client.post(f"/v1/demandes/{d2['id']}/approuver", json={"credential": faux.signer(defi)})
    ).status_code == 403
    assert await nb_audit(pool, "demande.cle_refusee") >= 3


async def test_cle_d_acces_refusee_sur_une_adresse_ip(systeme: dict[str, Any]) -> None:
    rep = await systeme["client"].post("/v1/cles/enregistrement/options", headers={"Host": "127.0.0.1:8765"})
    assert rep.status_code == 400 and "localhost" in rep.json()["detail"]


# --- Arrêt d'urgence ------------------------------------------------------------------------------------


async def test_arret_d_urgence_coupe_tout_en_moins_d_une_seconde(systeme: dict[str, Any], pool: Base) -> None:
    ctx: Contexte = systeme["ctx"]
    client = systeme["client"]
    lent: MoteurEspion = systeme["lent"]

    async def reponse_en_cours() -> None:
        with ctx.urgence.suivre():
            async for _ in ctx.service.repondre("Longue réponse", moteur="lent"):
                pass

    tache = asyncio.create_task(reponse_en_cours())
    while ctx.urgence.en_cours == 0 or not lent.recus:  # noqa: ASYNC110 — on attend une autre tâche
        await asyncio.sleep(0.01)
    debut = time.perf_counter()
    rep = (await client.post("/v1/urgence/arreter")).json()
    with pytest.raises(asyncio.CancelledError):
        await tache
    assert time.perf_counter() - debut < 1.0 and lent.annule.is_set()
    assert rep["reponses_interrompues"] == 1 and rep["urgence"]["actif"] is True
    # Écritures refusées (423), lectures permises
    bloque = await client.post("/v1/dialogue", json={"message": "x"})
    assert bloque.status_code == 423 and "urgence" in bloque.json()["detail"].lower()
    assert (await client.get("/v1/etat")).json()["urgence"]["actif"] is True
    # L'état survit à un redémarrage
    assert (await pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'arret_urgence'"))["actif"] is True
    # Lever = action 🔴 : clé d'accès obligatoire
    demande = (await client.post("/v1/urgence/lever")).json()["demande"]
    assert (await client.post(f"/v1/demandes/{demande['id']}/approuver", json={})).status_code == 409
    cle = await enregistrer_cle(client)
    defi = (await client.post(f"/v1/demandes/{demande['id']}/options")).json()
    leve = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={"credential": cle.signer(defi)})
    assert leve.status_code == 200 and ctx.urgence.actif is False
    assert (await client.post("/v1/dialogue", json={"message": "reprise"})).status_code == 200
    assert await nb_audit(pool, "urgence.arret") >= 1


# --- Filtre avant les fournisseurs externes --------------------------------------------------------------

# Valeurs factices, assemblées à l'exécution : aucun texte du dépôt ne ressemble à un vrai secret.
SECRETS = {
    "clé": "sk-" + "ant-api03-" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "e-mail": "jean.dupont" + "@" + "exemple.fr",
    "téléphone": "06 12 34 56 78",
    "iban": "FR76 3000 6000 0112 3456 7890 189",
    "carte": "4970 1012 3456 7893",  # clé de Luhn valide
}
URL_AVEC_MOT_DE_PASSE = "postgresql://moi:" + "motdepasse" + "@hote/base"
MOT_DE_PASSE = "pass" + "word=hunter2hunter2"


def test_filtre_masque_secrets_et_donnees_personnelles() -> None:
    texte = " ; ".join([*SECRETS.values(), URL_AVEC_MOT_DE_PASSE, MOT_DE_PASSE])
    r = masquer(texte)
    for valeur in [*SECRETS.values(), "motdepasse", "hunter2hunter2"]:
        assert valeur not in r.texte
    assert r.masques["E-MAIL"] == 1 and r.masques["TÉLÉPHONE"] == 1 and r.masques["IBAN"] == 1
    assert r.masques["CARTE BANCAIRE"] == 1
    # Pas de faux positif sur un texte ordinaire (numéro invalide, montant, date)
    ordinaire = "Le 12/03/2026, 1 500 € ; commande 1234 5678 9012 3456 ; IBAN FR00 1234 5678 9012"
    assert masquer(ordinaire).texte == ordinaire


async def test_aucun_secret_n_atteint_un_fournisseur_externe(systeme: dict[str, Any], pool: Base) -> None:
    ctx: Contexte = systeme["ctx"]
    espion: MoteurEspion = systeme["espion"]
    local: MoteurLocal = systeme["local"]
    message = f"Ma clé est {SECRETS['clé']} et mon e-mail {SECRETS['e-mail']}, appelle le {SECRETS['téléphone']}"
    evenements = [ev async for ev in ctx.service.repondre(message, moteur="espion")]
    envoye = "\n".join(m.contenu for m in espion.recus)
    for valeur in (SECRETS["clé"], SECRETS["e-mail"], SECRETS["téléphone"]):
        assert valeur not in envoye
    assert "[SECRET : clé d'API]" in envoye and evenements[-1].donnees["masques"]["E-MAIL"] == 1
    # La conversation stockée garde le texte d'origine ; un modèle LOCAL le reçoit tel quel
    conv = uuid.UUID(evenements[0].donnees["conversation_id"])
    assert await pool.fetchval("SELECT contenu FROM messages WHERE role = 'utilisateur'") == message
    _ = [ev async for ev in ctx.service.repondre("Et ensuite ?", conversation_id=conv, moteur="local")]
    assert SECRETS["clé"] in "\n".join(m.contenu for m in local.recus)


async def test_reponse_locale_privee_masquee_pour_l_externe(systeme: dict[str, Any]) -> None:
    ctx: Contexte = systeme["ctx"]
    espion: MoteurEspion = systeme["espion"]
    conv = await ctx.depot.creer("Privé")
    await ctx.depot.ajouter_message(conv.id, "utilisateur", "Rappelle-moi ce que tu sais de ma santé")
    await ctx.depot.ajouter_message(
        conv.id, "jarvis", "Votre dernier bilan date de mars", {"moteur": "local", "prive": True}
    )
    _ = [ev async for ev in ctx.service.repondre("Résume", conversation_id=conv.id, moteur="espion")]
    contenus = [m.contenu for m in espion.recus]
    assert TEXTE_MASQUE in contenus and "bilan date de mars" not in "\n".join(contenus)


def test_serveur_refuse_le_reseau_sans_choix_explicite(monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis2 import __main__ as principal
    from jarvis2.config import parametres

    monkeypatch.setenv("JARVIS2_HOTE", "0.0.0.0")  # noqa: S104 — c'est précisément ce qui doit être refusé
    parametres.cache_clear()
    try:
        assert principal.main(["serveur"]) == 2
    finally:
        parametres.cache_clear()
