# Les Emplois - style guide

This guide highlights **repository-specific CSS/HTML conventions** in the repo. It assumes familiarity with **Bootstrap 5.3** and focuses only on custom classes, patterns, and habits unique to this codebase.

---

## 🎨 Custom CSS Class Naming Conventions

### Component Prefix: `c-`
Custom components use the `c-` prefix:

- **`c-box`** - Generic box component
  - `c-box--structure` - Structure information box
  - `c-box--action-tooltip` - Box with tooltip (z-index: 1050 !important)
  - `c-box__header--dora`, `c-box__header--diagoriente`, `c-box__header--gps`, `c-box__header--immersion-facile` - Dashboard card headers with background images

- **`c-banner`** - Banner components
  - `c-banner--pilotage` - Dashboard statistics banner with background image

- **`c-form`** - Form container wrapper

- **`c-search`** - Search component
  - `c-search__bar` - Search bar sub-component

### Section Prefix: `s-`
Sections and layouts use the `s-` prefix:

- **`s-section`** - Main section wrapper
  - `s-section__container` - Section container (usually with Bootstrap `.container`)
  - `s-section__row` - Section row (usually with Bootstrap `.row`)
  - `s-section__col` - Section column (usually with Bootstrap `.col-*`)

- **`s-tabs-01`** - Tab navigation component
  - `s-tabs-01__nav` - Tab navigation list

---

## 🎯 Data Attribute Conventions

### JavaScript Prefixes

The project uses **three distinct prefixes** for data attributes:

1. **`data-bs-`** - Reserved for Bootstrap 5 native functionality
2. **`data-it-`** - Used by the [itou-theme](https://github.com/gip-inclusion/itou-theme)
3. **`data-emplois-`** - **Project-specific JavaScript behaviors** (preferred for new code)

#### Common `data-emplois-` Attributes

```html
<!-- Set input values from buttons -->
<button data-emplois-setter-target="#id_order"
        data-emplois-setter-value="asc">
</button>

<button data-emplois-setter-target="#checkbox-id"
        data-emplois-setter-checked="true">
</button>

<!-- Sync checkbox states between two inputs -->
<input type="checkbox" data-emplois-sync-with="other-checkbox-id">

<!-- Select all checkboxes -->
<input type="checkbox" data-emplois-select-all-target-input-name="field_name">

<!-- Control element visibility based on selection -->
<form data-emplois-elements-visibility-on-selection-controller="checkbox_name">
  <div data-emplois-elements-visibility-on-selection="hidden">...</div>
  <div data-emplois-elements-visibility-on-selection="shown">...</div>
  <div data-emplois-elements-visibility-on-selection="disabled">...</div>
</form>

<!-- Auto-focus on error -->
<div tabindex="0" data-emplois-give-focus-if-exist>Error message</div>
```

#### `data-it-` Attributes (from itou-theme)

```html
<!-- Sliding tabs with Tiny Slider -->
<ul class="s-tabs-01__nav nav nav-tabs"
    data-it-sliding-tabs="true"
    data-it-sliding-tabs-startindex="2">
```

---

## 🏷️ Badge Conventions

### Badge Size Modifiers
- `badge-xs` - Extra small badge
- `badge-sm` - Small badge (default if not specified)
- `badge-base` - Base size badge

### Badge Color Schemes
Badges use **contextual background and text color combinations**:

```html
<!-- Success states -->
<span class="badge badge-sm rounded-pill bg-success-lighter text-success">
  <i class="ri-check-line" aria-hidden="true"></i>
  Status text
</span>

<!-- Info states -->
<span class="badge badge-xs rounded-pill bg-info-lighter text-info">
  <i class="ri-verified-badge-fill" aria-hidden="true"></i>
  Certifié
</span>

<!-- Danger states -->
<span class="badge badge-xs rounded-pill bg-danger-lighter text-danger">
  <i class="ri-error-warning-fill" aria-hidden="true"></i>
  Error text
</span>

<!-- Accent colors -->
<span class="badge badge-xs rounded-pill bg-accent-02-light text-primary">
  Accent badge
</span>

<span class="badge badge-sm rounded-pill bg-accent-03 text-primary">
  À contrôler
</span>

<!-- Custom employment color -->
<span class="badge badge-sm rounded-pill bg-emploi-light text-primary">
  Employment related
</span>

<span class="badge badge-sm rounded-pill bg-emploi-light text-info rounded-pill">
  Count badge
</span>

<!-- Accent 01 -->
<span class="badge badge-sm rounded-pill bg-accent-01-lightest text-accent-01">
  Special accent
</span>
```

**Pattern:** Badges almost always use `rounded-pill` shape.

---

## 🎨 Icon System: Remix Icon

The project uses **[Remix Icon](https://remixicon.com/)** with the `ri-` prefix:

```html
<i class="ri-community-line" aria-hidden="true"></i>
<i class="ri-map-pin-2-line fw-normal me-2" aria-hidden="true"></i>
<i class="ri-verified-badge-fill" aria-hidden="true"></i>
<i class="ri-function-line ri-xl fw-normal text-disabled"></i>
<i class="ri-information-line ri-xl text-info" aria-hidden="true"></i>
```

### Icon Size Modifiers
- `ri-lg` - Large icon
- `ri-xl` - Extra large icon

**Always include** `aria-hidden="true"` for decorative icons.

---

## 📦 Custom Utility Classes

### Form-Specific

```css
.form-checkbox-greater-spacing > .form-check {
    margin-bottom: .75rem;
}

.form-group.is-invalid > .file-dropzone {
    border: 2px dashed var(--bs-danger);
}
```

### File Dropzone

```css
.file-dropzone {
    width: 100%;
    border: 2px dashed var(--bs-gray-700);
    border-radius: 0.25rem;
    text-align: center;
    padding: 1rem;
    margin-bottom: 0.5rem;
}

.file-dropzone.highlighted {
    opacity: 0.5;
}
```

### Custom Responsive Utilities

```css
@media (min-width: 768px) {
    .fixed-sm-bottom {
        position: fixed !important;
        right: 0;
        bottom: 0;
        z-index: 1030;
    }
}
```

### Border Utilities

```css
.border-dashed {
    border-style: dashed !important;
}
```

### Z-Index Overrides

```css
.c-box--action-tooltip {
  z-index: 1050 !important;
}

.modal-tooltip {
  z-index: 3055 !important;
}

.select2-dropdown {
    z-index: 4051 !important;
}
```

### Custom Heading Classes

```css
.h1-hero-c1 {
    font-size: 2.5rem;
    margin-bottom: 1.5rem;
}

@media (min-width: 1024px) {
    .h1-hero-c1 {
        margin-bottom: 3rem;
    }
}
```

### Card Deck Custom

```css
.card-deck-itou {
    text-align: center;
    justify-content: space-between;
}

.card-deck-itou > .card {
    position: relative;
    padding: 1.5rem;
}
```

---

## 🔧 Select2 Customizations

```css
/* Force width */
.form-group > .select2-container--bootstrap-5 {
    width: 100% !important;
}

/* Text wrapping */
.select2-selection__rendered {
    white-space: break-spaces !important;
}

/* Scrollable dropdown */
.dropdown-menu {
    max-height: 360px;
    overflow-y: auto;
}
```

---

## 🖱️ ProConnect Button

Custom authentication button styling:

```css
.proconnect-button {
  background-color: transparent !important;
  background-image: url("../img/pro_connect_bouton.svg");
  background-position: 50% 50%;
  background-repeat: no-repeat;
  width: 214px;
  height: 56px;
  display: inline-block;
}

.proconnect-button:hover {
  background-image: url("../img/pro_connect_bouton_hover.svg");
}
```

---

## 🧩 Django Template Components

The project uses **Django component fragments** extensively:

```django
{% component_title c_title__main=c_title__main %}
    {% fragment as c_title__main %}
        <h1>Page Title</h1>
    {% endfragment %}
{% endcomponent_title %}
```

Common pattern in templates:
- `{% load components %}` at the top
- `component_title` with fragments for title sections
- Fragments defined with `{% fragment as variable_name %}`

---

## 📐 Layout Patterns

### Standard Section Structure

```html
<section class="s-section">
    <div class="s-section__container container">
        <div class="s-section__row row">
            <div class="s-section__col col-12 col-xxl-8 col-xxxl-9">
                <!-- Main content -->
            </div>
            <div class="s-section__col col-12 col-xxl-4 col-xxxl-3">
                <!-- Sidebar content -->
            </div>
        </div>
    </div>
</section>
```

### Tab Navigation Pattern

```html
<ul class="s-tabs-01__nav nav nav-tabs mb-0" data-it-sliding-tabs="true">
    <li class="nav-item">
        <a class="nav-link active" href="#">Tab 1</a>
    </li>
    <li class="nav-item">
        <a class="nav-link" href="#">Tab 2</a>
    </li>
</ul>
```

---

## 🎯 Accessibility Patterns

- Always use `aria-hidden="true"` for decorative icons
- Use `aria-label` for buttons without visible text
- Include `role="status"` or `role="alert"` for alerts
- Use `tabindex="0"` with `data-emplois-give-focus-if-exist` for error messages
- Use `aria-controls`, `aria-expanded` for collapsible elements

---

## ⚠️ Browser-Specific Fixes

### Firefox Invalid Input Styling

```css
/* Disable Firefox red box-shadow on invalid inputs */
.home-search :not(output):-moz-ui-invalid:not(:focus) {
    box-shadow: none;
}
```

---

## 📝 Important Notes

1. **No SCSS**: This project uses plain CSS (no `.scss` files in the codebase)
2. **Migration in progress**: The team is actively migrating from class-based to `data-emplois-` prefixed JavaScript selectors
3. **Modal placement**: There's an ongoing migration to move modals to `<body>` level to avoid z-index issues
4. **Tooltip positioning**: Special z-index classes (`c-box--action-tooltip`, `modal-tooltip`) handle specific overlay scenarios
