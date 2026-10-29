# Code Connect — UI-Kit Figma ↔ les-emplois

Ce dossier relie les composants de l'[UI-Kit Figma](https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit)
au HTML réellement utilisé dans les-emplois (Bootstrap 5 + [itou-theme](https://gip-inclusion.github.io/itou-theme/doc/)).

Quand on inspecte une maquette en mode Dev dans Figma, chaque composant relié affiche
l'extrait de code correspondant, avec les classes qui suivent les réglages de l'instance
(taille, état, icône…), au lieu du CSS généré par Figma.

Rien ici n'est chargé par l'application : ce sont des fichiers de documentation lus
uniquement par l'outil [Code Connect](https://developers.figma.com/docs/code-connect/).

## Contenu

- `figma.config.json` : configuration de l'outil (libellé « HTML »).
- `components/*.figma.js` : un fichier par composant Figma. La première ligne `// url=`
  désigne le composant dans Figma, `// source=` le gabarit ou la story d'où vient le balisage.

Les icônes (Remix Icon, `<i class="ri-…">`), les logos et les illustrations ne sont pas reliés :
leur nom dans Figma suffit.

## Vérifier les fichiers

```bash
cd figma
npx -y @figma/code-connect@2.0.1 connect parse
```

## Publier dans Figma

Il faut un jeton d'accès Figma personnel avec le droit « Code Connect : écriture »
(Figma → Settings → Security → Personal access tokens), exporté dans l'environnement.
Ne jamais le committer.

```bash
cd figma
FIGMA_ACCESS_TOKEN=… npx -y @figma/code-connect@2.0.1 connect publish
```

Republier après chaque modification d'un fichier : la nouvelle version remplace l'ancienne.

## Quand un composant change

- **Le HTML change dans les-emplois** : mettre à jour le fichier `components/<composant>.figma.js`
  correspondant, puis republier.
- **Le composant change dans Figma** (propriété renommée, nouvelle variante) : mettre à jour
  les noms de propriétés et les valeurs dans le fichier, puis republier. Un nom de propriété
  inconnu fait échouer l'affichage de l'extrait dans Figma.
- **Nouveau composant** : copier un fichier existant, changer l'`url`, la `source` et l'`id`.
