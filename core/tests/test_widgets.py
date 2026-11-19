"""Phase 14, D 16 : widgets générés à la demande (fragment validé par le Core), épinglage, phrase d'attente."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import attente, widgets
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.base import Delta, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.securite import appareils

ORIGINE = "http://localhost:8765"

MINUTEUR = (
    '<div class="w-carte"><p class="w-libelle">Infusion</p>'
    '<time class="w-minuteur w-geant" data-minuteur="240">4:00</time></div>'
)


# --- Validation du fragment (sans base) ----------------------------------------------------------------------


def test_fragment_conforme_reecrit() -> None:
    propre = widgets.valider_fragment(MINUTEUR)
    assert propre == MINUTEUR
    liste = widgets.valider_fragment(
        "<ul class='w-liste'><li>Pain &amp; beurre</li><li class=\"w-coche\">Lait</li></ul>"
        '<meter class="w-jauge" value="0.4" min="0" max="1">40 %</meter><a href="#memoire">Mémoire</a><br>'
    )
    # Guillemets normalisés, texte échappé, rien d'autre
    assert liste.startswith('<ul class="w-liste"><li>Pain &amp; beurre</li>')
    assert '<a href="#memoire">' in liste and liste.endswith("<br>")


def test_texte_qui_ressemble_a_du_html_reste_du_texte() -> None:
    propre = widgets.valider_fragment("<p>1 &lt;script&gt;alert(1)&lt;/script&gt;</p>")
    assert "<script" not in propre and "&lt;script&gt;" in propre


MALVEILLANTS = {
    "script": "<p>Bonjour</p><script>alert(1)</script>",
    "script majuscules": "<SCRIPT SRC=//x.example/a.js></SCRIPT>",
    "onerror": '<img src="x" onerror="alert(1)">',
    "onclick sur une balise permise": '<p onclick="alert(1)">Cliquez</p>',
    "onmouseover sans guillemets": "<span onmouseover=alert(1)>x</span>",
    "javascript:": '<a href="javascript:alert(1)">ici</a>',
    "javascript: encodé": '<a href="&#106;avascript&#58;alert(1)">ici</a>',
    "javascript: avec espaces": '<a href=" javascript:alert(1)">ici</a>',
    "adresse externe": '<a href="https://exemple.org">site</a>',
    "adresse protocole relatif": '<a href="//exemple.org">site</a>',
    "data:": '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
    "ancre vers une vue inconnue": '<a href="#ailleurs">x</a>',
    "style en ligne": '<p style="background:url(javascript:alert(1))">x</p>',
    "balise style": "<style>p{color:red}</style><p>x</p>",
    "iframe": '<iframe src="https://exemple.org"></iframe>',
    "iframe srcdoc": '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    "svg piégé": "<svg><script>alert(1)</script></svg>",
    "svg onload": '<svg onload="alert(1)"><circle r="4"/></svg>',
    "svg animate": '<svg><a><animate attributeName="href" values="javascript:alert(1)"/></a></svg>',
    "math": "<math><mtext><img src=x onerror=alert(1)></mtext></math>",
    "classe inconnue": '<div class="w-carte rouge-vif">x</div>',
    "classe d'un autre composant": '<div class="btn-principal">x</div>',
    "objet": '<object data="x.swf"></object>',
    "formulaire": '<form action="https://exemple.org"><input name="mdp"></form>',
    "commentaire conditionnel": "<!--[if IE]><script>alert(1)</script><![endif]-->",
    "cdata": "<![CDATA[<script>alert(1)</script>]]>",
    "attribut inconnu": '<p data-x="1">x</p>',
    "data-minuteur hors de time": '<p data-minuteur="60">x</p>',
    "href hors de a": '<p href="#memoire">x</p>',
    "valeur non numérique": '<meter value="calc(1)">x</meter>',
    "balise non fermée": "<div><p>x</p>",
    "mal imbriqué": "<div><p>x</div></p>",
    "base": '<base href="https://exemple.org/">',
    "meta refresh": '<meta http-equiv="refresh" content="0;url=https://exemple.org">',
    "lien feuille": '<link rel="stylesheet" href="https://exemple.org/a.css">',
    "texte seul": "Rien que du texte",
}


@pytest.mark.parametrize("nom", list(MALVEILLANTS))
def test_fragments_malveillants_rejetes(nom: str) -> None:
    with pytest.raises(widgets.FragmentRefuse):
        widgets.valider_fragment(MALVEILLANTS[nom])


def test_limites() -> None:
    with pytest.raises(widgets.FragmentRefuse, match="caractères"):
        widgets.valider_fragment("<p>" + "x" * widgets.TAILLE_MAX_FRAGMENT + "</p>")
    with pytest.raises(widgets.FragmentRefuse, match="niveaux"):
        widgets.valider_fragment("<div>" * 9 + "x" + "</div>" * 9)
    with pytest.raises(widgets.FragmentRefuse, match="éléments"):
        widgets.valider_fragment("<br>" * (widgets.NB_MAX_ELEMENTS + 1))


def test_extraction_du_bloc() -> None:
    texte = (
        f'Voici votre minuteur.\n<widget titre="Thé">{MINUTEUR}</widget>\n'
        '<widget titre="Piège"><img src=x onerror=alert(1)></widget>'
        "<widget titre='Ouvert'><p>sans fin"
    )
    ex = widgets.extraire(texte)
    assert ex.texte == "Voici votre minuteur."
    assert [w["titre"] for w in ex.widgets] == ["Thé"]
    assert ex.widgets[0]["html"] == MINUTEUR and len(ex.widgets[0]["id"]) == 16
    assert any("Piège" in e and "img" in e for e in ex.ecartes)
    assert any("non fermé" in e for e in ex.ecartes)
    assert "onerror" not in json.dumps(ex.meta()) and "alert" not in json.dumps(ex.meta())  # jamais le contenu refusé


def test_sans_bloc_rien_ne_change() -> None:
    ex = widgets.extraire("Une simple réponse avec <widgets au pluriel> écrits.")
    assert ex.texte == "Une simple réponse avec <widgets au pluriel> écrits." and ex.meta() == {}


def test_trois_widgets_au_plus_et_titre_borne() -> None:
    bloc = "".join(f'<widget titre="{"T" * 80}{i}"><p>{i}</p></widget>' for i in range(5))
    ex = widgets.extraire("Ok." + bloc)
    assert len(ex.widgets) == widgets.NB_MAX_WIDGETS
    assert all(len(w["titre"]) <= widgets.TAILLE_MAX_TITRE for w in ex.widgets)
    assert any("plus de 3" in e for e in ex.ecartes)


def test_phrase_d_attente() -> None:
    assert attente.evenement("conseil")["phrase"].startswith("Je consulte")
    assert attente.evenement("inconnu") == {"outil": "autre", "phrase": attente.phrase("inconnu")}


# --- Avec la base --------------------------------------------------------------------------------------------


class MoteurScript(Moteur):
    id = "script"
    nom = "Script"
    externe = False

    def __init__(self) -> None:
        self.texte = "Bonjour."
        self.recus: list[Message] = []

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        if not self.recus:
            self.recus = list(messages)
        yield Delta(self.texte)
        yield Fin(Reponse(self.texte, "script-1"))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele("script-1", "Script", True)]

    async def health(self) -> EtatSante:
        return EtatSante(True)


@pytest.fixture
async def systeme(pool: Base) -> dict[str, Any]:
    depot = DepotConversations(pool)
    script = MoteurScript()
    moteurs = {"script": MoteurInstrumente(script, EnregistreurMemoire())}
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "script"), "script")
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    entetes = {"Authorization": f"Bearer {jeton}", "Origin": ORIGINE}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGINE, headers=entetes)
    return {"client": client, "script": script}


async def dialoguer(client: httpx.AsyncClient, message: str) -> dict[str, dict[str, Any]]:
    evenements: dict[str, dict[str, Any]] = {}
    async with client.stream("POST", "/v1/dialogue", json={"message": message, "moteur": "script"}) as rep:
        assert rep.status_code == 200
        nom = ""
        async for ligne in rep.aiter_lines():
            if ligne.startswith("event: "):
                nom = ligne[7:]
            elif ligne.startswith("data: "):
                evenements[nom] = json.loads(ligne[6:])
    return evenements


@pytest.mark.base
async def test_widget_de_la_reponse_valide_et_retire(systeme: dict[str, Any], pool: Base) -> None:
    client, script = systeme["client"], systeme["script"]
    avant = await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'widgets.generes'")
    piege = '<widget titre="X"><script>alert(1)</script></widget>'
    script.texte = f'Minuteur prêt.<widget titre="Thé">{MINUTEUR}</widget>{piege}'
    fin = (await dialoguer(client, "Un minuteur de 4 minutes pour le thé"))["fin"]
    assert fin["texte"] == "Minuteur prêt."
    assert [w["titre"] for w in fin["widgets"]] == ["Thé"] and len(fin["widgets_ecartes"]) == 1
    stocke = await pool.fetchrow("SELECT contenu, meta FROM messages WHERE role = 'jarvis'")
    assert stocke is not None and "<widget" not in stocke["contenu"]
    meta = stocke["meta"] if isinstance(stocke["meta"], dict) else json.loads(stocke["meta"])
    assert meta["widgets"][0]["html"] == MINUTEUR and "alert" not in json.dumps(meta)
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'widgets.generes'") == avant + 1
    assert "<widget" in script.recus[0].contenu  # les consignes expliquent le bloc au modèle


@pytest.mark.base
async def test_epingler_lister_retirer(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    avant = await pool.fetchval("SELECT count(*) FROM audit WHERE action LIKE 'widgets.%'")
    rep = await client.post("/v1/widgets", json={"titre": "Thé", "html": MINUTEUR})
    assert rep.status_code == 200 and rep.json()["nouveau"] is True
    w = rep.json()["widget"]
    assert w["empreinte"] == widgets.empreinte("Thé", MINUTEUR) and w["html"] == MINUTEUR
    # Doublon : le même widget, rien de plus
    rep = await client.post("/v1/widgets", json={"titre": "Thé", "html": MINUTEUR})
    assert rep.json()["nouveau"] is False and rep.json()["widget"]["id"] == w["id"]
    # L'interface ne fait jamais foi : un fragment piégé est refusé à l'épinglage
    for piege in (MALVEILLANTS["onerror"], MALVEILLANTS["svg piégé"], MALVEILLANTS["classe inconnue"]):
        refus = await client.post("/v1/widgets", json={"titre": "Piège", "html": piege})
        assert refus.status_code == 422 and "refusé" in refus.json()["detail"]
    liste = (await client.get("/v1/widgets")).json()["widgets"]
    assert [x["id"] for x in liste] == [w["id"]]
    assert "widgets" in (await client.get("/v1/etat")).json()  # au démarrage : un seul appel
    assert (await client.delete(f"/v1/widgets/{w['id']}")).status_code == 200
    assert (await client.delete(f"/v1/widgets/{w['id']}")).status_code == 404
    assert (await client.get("/v1/widgets")).json()["widgets"] == []
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action LIKE 'widgets.%'") == avant + 2


@pytest.mark.base
async def test_plafond_d_epingles(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    for i in range(widgets.NB_MAX_EPINGLES):
        assert (await client.post("/v1/widgets", json={"titre": f"N{i}", "html": f"<p>{i}</p>"})).status_code == 200
    trop = await client.post("/v1/widgets", json={"titre": "Trop", "html": "<p>trop</p>"})
    assert trop.status_code == 422 and "au plus" in trop.json()["detail"]


@pytest.mark.base
async def test_fragment_devenu_non_conforme_n_est_plus_servi(systeme: dict[str, Any], pool: Base) -> None:
    await pool.execute(
        "INSERT INTO widgets_epingles (empreinte, titre, html) VALUES ($1, $2, $3)",
        "0123456789abcdef",
        "Ancien",
        '<p class="w-disparue">x</p>',
    )
    assert (await systeme["client"].get("/v1/widgets")).json()["widgets"] == []


@pytest.mark.base
async def test_phrase_d_attente_quand_des_images_sont_jointes(systeme: dict[str, Any]) -> None:
    """Analyse d'image : outil long, la phrase d'attente part avant la réponse."""
    client = systeme["client"]
    systeme["script"].vision = True  # sait lire les images : la réponse part (sinon : message clair, rien n'est envoyé)
    image = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAAB"
        "JRU5ErkJggg=="
    )
    noms: list[str] = []
    async with client.stream(
        "POST", "/v1/dialogue", json={"message": "Que vois-tu ?", "moteur": "script", "images": [image]}
    ) as rep:
        async for ligne in rep.aiter_lines():
            if ligne.startswith("event: "):
                noms.append(ligne[7:])
            elif ligne.startswith("data: ") and noms[-1] == "attente":
                assert json.loads(ligne[6:])["outil"] == "vision"
    assert noms.index("attente") < noms.index("fin"), noms


def test_memes_listes_que_l_interface() -> None:
    """Le filtre de l'interface (DOMPurify, widgets.ts) et la feuille widgets.css suivent les listes du Core."""
    racine = Path(__file__).resolve().parents[2] / "interface" / "src"
    source = racine / "widgets.ts"
    if not source.exists():
        pytest.skip("interface absente")
    ts = source.read_text(encoding="utf-8")

    def bloc(nom: str) -> set[str]:
        m = re.search(rf"{nom}[^=]*=[^\[]*\[(.*?)\]", ts, re.DOTALL)
        assert m is not None, nom
        return set(re.findall(r'"([a-z0-9-]+)"', m.group(1)))

    assert bloc("BALISES") == set(widgets.BALISES)
    assert bloc("CLASSES") == set(widgets.CLASSES)
    attributs = re.search(r"ATTRIBUTS[^=]*= \{(.*?)\n\};", ts, re.DOTALL)
    assert attributs is not None
    assert set(re.findall(r'^\s*"?([a-z-]+)"?: \{', attributs.group(1), re.MULTILINE)) == set(widgets.ATTRIBUTS)
    css = (racine / "styles" / "widgets.css").read_text(encoding="utf-8")
    assert all(f".{c} " in css or f".{c}," in css for c in widgets.CLASSES), "classe sans style"
