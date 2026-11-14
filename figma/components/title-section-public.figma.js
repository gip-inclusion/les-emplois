// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10565-5576
// source=les-emplois itou/templates/layout/base.html (section.s-title-02 + title_* blocks), components/c-navinfo.html, components/c-title.html; examples: search/siaes_search_results.html (c-search, tabs), apply/includes/siae_actions.html (action bar)
// component=Section titre déconnecté
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Titre')
const badge = instance.getBoolean('↳ Badge')
const actionBar = instance.getBoolean("Barre d'action")
const searchBar = instance.getBoolean('Barre de recherche')
const tabs = instance.getEnum('Onglets', { On: true, Off: false })

const lines = (...parts) => parts.filter(Boolean).join('\n')

const badgeHtml = badge ? '\n                <span class="badge badge-base rounded-pill bg-success">Label</span>' : ''

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
{% block title_navinfo %}
    {% component_navinfo c_navinfo__back_url=back_url %}
    {% endcomponent_navinfo %}
{% endblock %}
{% block title_content %}
    {% component_title c_title__main=c_title__main %}
        {% fragment as c_title__main %}
            <h1>
                ${title}${badgeHtml}
            </h1>
        {% endfragment %}
    {% endcomponent_title %}
{% endblock %}${titleExtra}`,
  id: 'title-section-public',
  metadata: { nestable: true },
}
