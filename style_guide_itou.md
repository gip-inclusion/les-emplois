# itou-theme — style guide

Thème Bootstrap 5.3 de la **Plateforme de l'Inclusion** (emplois, communauté, pilotage). Ce guide documente uniquement les **spécificités**, **appliquer Bootstrap 5.3 standard** pour tout le reste.

---

## Icônes : Remix Icons (pas Font Awesome)

Le thème utilise **exclusivement Remix Icons** — ne pas utiliser Font Awesome ou Bootstrap Icons.

```html
<i class="ri-home-line"></i>       <!-- outline → usage général -->
<i class="ri-check-fill"></i>      <!-- fill → état actif/validé -->
<i class="ri-arrow-right-line"></i>
```

Icône seule → toujours `aria-label` ou `<span class="visually-hidden">`.

---

## Conteneur standard

```html
<div class="container-xl">…</div>     <!-- c'est le standard itou (max-width: 1320px) -->
<div class="container">…</div>        <!-- à éviter -->
<div class="container-fluid">…</div>  <!-- sections pleine largeur uniquement -->
```

---

## Composants custom itou

Ces composants n'existent pas dans Bootstrap natif.

### Step List

Liste d'étapes numérotées, processus séquentiel.

```html
<ol class="s-step-list">
  <li class="s-step-list__item">
    <span class="s-step-list__number">1</span>
    <div class="s-step-list__content">
      <h3 class="s-step-list__title">Créer un compte</h3>
      <p>Description de l'étape.</p>
    </div>
  </li>
  <li class="s-step-list__item">…</li>
</ol>
```

- `<ol>` sémantique obligatoire (ordre important)
- Max ~7 étapes

### Stepper

Indicateur de progression pour formulaires multi-étapes.

```html
<div class="s-stepper">
  <div class="s-stepper__item s-stepper__item--done">
    <span class="s-stepper__icon"><i class="ri-check-line"></i></span>
    <span class="s-stepper__label">Profil</span>
  </div>
  <div class="s-stepper__item s-stepper__item--active">
    <span class="s-stepper__icon">2</span>
    <span class="s-stepper__label">Candidature</span>
  </div>
  <div class="s-stepper__item">
    <span class="s-stepper__icon">3</span>
    <span class="s-stepper__label">Confirmation</span>
  </div>
</div>
```

Modificateurs d'état : `--done`, `--active` (aucun = à venir). Max 5-6 étapes.

### Tags

Étiquettes de catégorisation : **différents des badges Bootstrap**.

```html
<!-- Informatifs (non-interactifs) -->
<span class="badge badge-sm rounded-pill text-bg-primary">CDI</span>
<span class="badge badge-sm rounded-pill text-bg-success">Disponible</span>
<span class="badge badge-sm rounded-pill text-bg-secondary">Temps partiel</span>

<!-- Supprimables -->
<span class="badge badge-sm rounded-pill text-bg-primary">
  CDI
  <button type="button" class="btn-close btn-close-sm" aria-label="Retirer CDI"></button>
</span>
```

Utiliser `badge-sm` + `rounded-pill` systématiquement pour les tags.

### List Data

Paires clé-valeur (fiches récap, détails d'une entité).

```html
<dl class="s-list-data">
  <div class="s-list-data__item">
    <dt class="s-list-data__label">Statut</dt>
    <dd class="s-list-data__value">Validé</dd>
  </div>
  <div class="s-list-data__item">
    <dt class="s-list-data__label">Date de début</dt>
    <dd class="s-list-data__value">12 janvier 2024</dd>
  </div>
</dl>
```

Toujours `<dl>` / `<dt>` / `<dd>` — jamais `<table>` pour des données non-tabulaires.

### Box

Encadré visuel pour grouper des informations connexes.

```html
<div class="s-box">
  <h2 class="s-box__title">Informations employeur</h2>
  <p>…contenu…</p>
</div>
```

Distinct de `.card` : pas d'image, pas d'action principale. Contexte : blocs d'information statique.

### Info (callout contextuel)

Message d'aide contextuelle — **différent des alertes système**.

```html
<div class="s-info">
  <i class="ri-information-line s-info__icon" aria-hidden="true"></i>
  <div class="s-info__content">
    <p>Ce champ est utilisé pour calculer votre éligibilité.</p>
  </div>
</div>
```

Pas pour les erreurs (→ `alert alert-danger`). Pas pour les succès (→ `alert alert-success`).

### Spinner

```html
<div class="spinner-border text-primary" role="status">
  <span class="visually-hidden">Chargement…</span>
</div>
```

Désactiver les contrôles interactifs pendant le chargement (`disabled` + `aria-disabled="true"`).

---

## Sections de mise en page

### Header

```html
<header class="s-header">
  <!-- Lien d'évitement — PREMIER élément obligatoire -->
  <a class="visually-hidden-focusable" href="#main">Aller au contenu principal</a>

  <nav class="navbar navbar-expand-lg s-header__navbar">
    <div class="container-xl">
      <a class="navbar-brand s-header__brand" href="/">
        <img src="/img/logo-inclusion.svg" alt="Les emplois de l'inclusion" height="40">
      </a>
      <ul class="navbar-nav s-header__nav">
        <li class="nav-item"><a class="nav-link" href="/…">Lien</a></li>
      </ul>
      <div class="s-header__actions">
        <a href="/connexion" class="btn btn-primary btn-sm">Se connecter</a>
      </div>
    </div>
  </nav>
</header>
<main id="main">…</main>
```

### Post Header

Zone de titre juste après le header — porte le `<h1>` de la page.

```html
<div class="s-post-header">
  <div class="container-xl">
    <h1 class="s-post-header__title">Résultats de recherche</h1>
    <p class="s-post-header__subtitle">247 offres trouvées</p>
  </div>
</div>
```

Un seul `<h1>` par page, dans le post-header. Ne pas répéter dans le contenu.

### Hero Title 01

```html
<section class="s-hero">
  <div class="container-xl">
    <h1 class="s-hero__title">Bienvenue sur les emplois de l'inclusion</h1>
    <p class="s-hero__subtitle">Recrutez ou postulez via les structures de l'insertion.</p>
    <div class="s-hero__actions">
      <a href="/recherche" class="btn btn-primary btn-lg">Rechercher une offre</a>
      <a href="/inscription" class="btn btn-outline-primary btn-lg">S'inscrire</a>
    </div>
  </div>
</section>
```

Max 2 CTA (1 primary + 1 outline). Usage : pages d'accueil uniquement.

### Footer

```html
<footer class="s-footer">
  <div class="container-xl">
    <nav class="s-footer__nav" aria-label="Liens légaux">
      <ul class="s-footer__links">
        <li><a href="/mentions-legales">Mentions légales</a></li>
        <li><a href="/accessibilite">Accessibilité : partiellement conforme</a></li>
        <li><a href="/confidentialite">Politique de confidentialité</a></li>
        <li><a href="/contact">Contact</a></li>
      </ul>
    </nav>
  </div>
</footer>
```

Liens obligatoires : Mentions légales, Accessibilité (avec niveau de conformité), Confidentialité.

---

## Conventions clés

**`<a>` vs `<button>`** — Navigation = `<a href>`. Action = `<button type="button">`. Jamais `<div>` ou `<span>` cliquables.

**Un seul `btn-primary` par section** — le second CTA devient `btn-secondary` ou `btn-outline-primary`.

**Hiérarchie des titres** — Choisir le niveau sémantiquement correct, surcharger visuellement avec `.h3`, `.fs-4`, etc. Ne pas choisir `h5` pour son apparence.

**SCSS** — Variables avant import Bootstrap, jamais `!important`, jamais modifier `node_modules/`.

```scss
// ✅
$primary: #3A7FCC;
@import "bootstrap";
```

---

## Bibliothèques tierces

| Lib | Usage |
|---|---|
| **Remix Icons** | Icônes (remplace FA/BI) |
| Accessible Autocomplete | Champs de recherche avec suggestions |
| Duet Date Picker | Sélecteur de date (a11y) |
| Select 2 | `<select>` enrichi |
| Tarte au citron | Bandeau RGPD |
| Tiny Slider 2 | Carrousel |
| Lottie | Animations JSON |
| Intro.js | Tutoriels interactifs |

---

## Accessibilité (service public — obligation légale)

- Cible : WCAG AA
- Ne jamais retirer le `:focus` visible (le thème fournit un style de focus custom)
- `aria-label` sur tout lien générique : `aria-label="Voir l'offre : Développeur Python"`
- Lien d'évitement `#main` obligatoire dans chaque header
- Mention de conformité dans le footer : "totalement / partiellement / non conforme"
- Préférer les composants accessibles intégrés (Duet, Accessible Autocomplete…) à des alternatives tierces
