## Ce que change cette demande


## Issue liée

Ferme #<!-- numéro de l'issue, ou « Aucune » -->

## Type de changement

- [ ] Correction de bogue
- [ ] Nouvelle fonction
- [ ] Changement de comportement existant (à signaler dans le CHANGELOG)
- [ ] Sécurité
- [ ] Documentation seulement
- [ ] Maintenance (CI, dépendances, outillage, tests)

## Vérifié

- [ ] `uv run pytest`, `ruff check`, `ruff format --check`, `mypy` (core)
- [ ] `npm run verifier` et `npm run build` (interface)
- [ ] Tests ajoutés ou mis à jour pour ce qui change
- [ ] Interface : 375, 1280 et 1920 px, console vide, jetons de `interface/DESIGN.md` (si l'interface change)
- [ ] Migrations jumelles PostgreSQL et SQLite (si le schéma change)
- [ ] Permissions 🟢🟡🔴, approbations et audit respectés (si une action est ajoutée)
- [ ] Rien de personnel ni de secret dans le code, les tests, les captures ou l'historique
- [ ] Textes, commentaires et commits en français

## Documentation

- [ ] `CHANGELOG.md` mis à jour (section « Unreleased »)
- [ ] README, `docs/` (plan, décisions, guides) mis à jour si besoin
- [ ] Rien à documenter
