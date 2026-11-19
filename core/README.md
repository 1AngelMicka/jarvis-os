# JARVIS 2 — Core

Assistant personnel local : API, moteurs d'IA, mémoire et interface web (précompilée, incluse dans le paquet).
Stockage SQLite par défaut, PostgreSQL en option. Python 3.13.

## Installer avec pipx

```sh
pipx install --python 3.13 jarvis2-x.y.z-py3-none-any.whl   # roue jointe à chaque version publiée
jarvis2 docteur --reparer                                    # base SQLite et modèle d'embeddings (une fois)
jarvis2                                                      # lance le Core et ouvre http://localhost:8765
```

Depuis le dépôt : `cd interface ; npm install ; npm run build`, puis `pipx install --python 3.13 ./core`
(sans interface compilée, le paquet s'installe sans elle et `jarvis2 docteur` le signale).

Commandes : `jarvis2 --help`. Documentation complète, installeurs et application de bureau :
<https://github.com/1AngelMicka/jarvis-os>.

Licence Apache 2.0.
