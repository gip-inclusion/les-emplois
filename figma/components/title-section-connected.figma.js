// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10420-13464
// source=les-emplois itou/templates/layout/base.html (section.s-title-02 + title_* blocks), components/c-navinfo.html, components/c-title.html; examples: companies/job_description_card.html (navinfo info), apply/process_base.html (print + badge), apply/list_for_siae.html (cta), apply/includes/siae_actions.html (action bar), search/siaes_search_results.html (c-search), apply/includes/job_applications_filters/top_filters.html (filters), companies/job_description_list.html (tabs)
// component=Section titre connecté
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Titre')
const back = instance.getBoolean('Retour')
const hasDate = instance.getBoolean('Date')
const date = hasDate ? instance.getString('↳ Text date') : ''
const badge = instance.getBoolean('Badge')
const hasSubtitle = instance.getBoolean('Sous-titre')
const subtitle = hasSubtitle ? instance.getString('↳ Text sous-titre') : ''
const print = instance.getBoolean('Bouton imprimer')
const secondaryAction = instance.getBoolean('Action secondaire')
const primaryAction = instance.getBoolean('Action principale')
const sectionH2 = instance.getEnum('Section H2', { On: true, Off: false })
const hasH2 = sectionH2 && instance.getBoolean('Titre H2')
const h2 = hasH2 ? instance.getString('↳ Text titre H2') : ''
const hasH2Subtitle = sectionH2 && instance.getBoolean('Sous-titre H2')
const h2Subtitle = hasH2Subtitle ? instance.getString('↳ Text sous-titre H2') : ''
const actionBar = instance.getEnum("Barre d'action", { On: true, Off: false })
const searchBar = instance.getBoolean('Barre de recherche')
const filters = instance.getBoolean('Filtres')
const tabs = instance.getEnum('Onglet', { On: true, Off: false })

const lines = (...parts) => parts.filter(Boolean).join('\n')

// --- {% block title_navinfo %} — c-navinfo renders nothing without back_url or info.
let navinfo = ''
if (back || hasDate) {
  const args = lines(back ? ' c_navinfo__back_url=back_url' : '', hasDate ? ' c_navinfo__info=c_navinfo__info' : '').replace(/\n/g, '')
  navinfo = `{% block title_navinfo %}
    {% component_navinfo${args} %}${hasDate ? `
        {% fragment as c_navinfo__info %}
            ${date}
        {% endfragment %}` : ''}
    {% endcomponent_navinfo %}
{% endblock %}
`
}

// --- {% block title_content %} — c-title
const badgeHtml = badge ? '\n                <span class="badge badge-base rounded-pill bg-success">Label</span>' : ''
const main = lines(
  `            <h1>
                ${title}${badgeHtml}
            </h1>`,
  hasSubtitle ? `            <p>${subtitle}</p>` : ''
)
const cta = lines(
  print
    ? `            <button class="btn btn-lg btn-ico-only btn-link" type="button" data-it-action="print" aria-label="Imprimer …">
                <i class="ri-printer-line fw-normal" aria-hidden="true"></i>
            </button>`
    : '',
  secondaryAction
    ? `            <a href="…" class="btn btn-lg btn-ico btn-secondary">
                <i class="ri-download-line fw-medium" aria-hidden="true"></i>
                <span>Action secondaire</span>
            </a>`
    : '',
  primaryAction
    ? `            <a href="…" class="btn btn-lg btn-primary btn-ico">
                <i class="ri-draft-line fw-medium" aria-hidden="true"></i>
                <span>Action principale</span>
            </a>`
    : ''
)
const secondary = lines(hasH2 ? `            <h2>${h2}</h2>` : '', hasH2Subtitle ? `            <p>${h2Subtitle}</p>` : '')
const titleArgs = [' c_title__main=c_title__main', cta ? ' c_title__cta=c_title__cta' : '', secondary ? ' c_title__secondary=c_title__secondary' : ''].join('')
const titleContent = `{% block title_content %}
    {% component_title${titleArgs} %}
        {% fragment as c_title__main %}
${main}
        {% endfragment %}${cta ? `
        {% fragment as c_title__cta %}
${cta}
        {% endfragment %}` : ''}${secondary ? `
        {% fragment as c_title__secondary %}
${secondary}
        {% endfragment %}` : ''}
    {% endcomponent_title %}
{% endblock %}`

// --- {% block title_extra %}
const extra = lines(
  actionBar
    ? `    <div class="c-box c-box--action">
        <h2 class="visually-hidden">Actions rapides</h2>
        <div class="form-row align-items-center gx-3">…</div>
    </div>`
    : '',
  searchBar
    ? `    <div class="c-search mt-3 mt-md-4">
        <div class="c-search__bar">
            <form>
                {% include "search/includes/siaes_search_form.html" with form=form is_home=False only %}
            </form>
        </div>
    </div>`
    : '',
  filters
    ? `    <div class="btn-dropdown-filter-group mb-3 mb-md-4">
        {% include "includes/btn_dropdown_filter/radio.html" with field=form.distance id_suffix="-top" only %}
        <button type="button" class="btn btn-ico btn-dropdown-filter" data-bs-toggle="offcanvas" data-bs-target="#offcanvasApplyFilters" aria-controls="offcanvasApplyFilters">
            <i class="ri-sound-module-fill fw-medium" aria-hidden="true"></i>
            <span>Tous les filtres</span>
        </button>
        <div class="ms-md-auto">
            <a href="…" class="btn btn-ico btn-dropdown-filter" aria-label="Réinitialiser les filtres actifs">
                <i class="ri-eraser-line fw-medium" aria-hidden="true"></i>
                <span>Effacer tout</span>
            </a>
        </div>
    </div>`
    : '',
  tabs
    ? `    <ul class="s-tabs-01__nav nav nav-tabs mb-0" data-it-sliding-tabs="true">
        <li class="nav-item">
            <a class="nav-link active" href="…">Onglet 1</a>
        </li>
        <li class="nav-item">
            <a class="nav-link" href="…">Onglet 2</a>
        </li>
    </ul>`
    : ''
)
const titleExtra = extra ? `
{% block title_extra %}
${extra}
{% endblock %}` : ''

export default {
  example: figma.html`{# In a page that {% extends "layout/base.html" %}: base.html wraps these blocks in section.s-title-02 #}
${navinfo}${titleContent}${titleExtra}`,
  id: 'title-section-connected',
  metadata: { nestable: true },
}
