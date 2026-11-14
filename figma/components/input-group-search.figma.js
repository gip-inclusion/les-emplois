// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10434-5815
// source=les-emplois: itou/templates/search/includes/siaes_search_form.html (same structure in prescribers_search_form.html and search/services/includes/form.html)
// component=input group search
const figma = require('figma')
const instance = figma.selectedInstance

// Accueil = the template's is_home=True branch; Résultats = is_home=False (results pages, dashboard).
const isHome = instance.getEnum('Contexte', { Accueil: true, 'Résultats': false })
const cityGroup = isHome ? 'input-group-lg' : 'input-group-xl input-group-search'
const labelPadding = isHome ? ' ps-0' : ''
const iconColor = isHome ? 'text-tertiary' : 'text-disabled'
const buttonGroup = isHome ? 'input-group-lg' : 'input-group-xl'
const buttonVariant = isHome ? 'btn-primary' : 'btn-link'

// The city <select> is a RemoteAutocompleteSelect2Widget ({{ form.city }}): the text shown in the field
// is select2's data-placeholder, not an HTML placeholder attribute.
export default {
  example: figma.html`<div class="c-search__bar__grid">
    <div class="input-group ${cityGroup} flex-nowrap align-items-center">
        <label class="input-group-text mb-0${labelPadding}" for="id_city">
            <span class="visually-hidden">Ville</span>
            <i class="ri-map-pin-line fw-medium ri-xl ${iconColor}" aria-hidden="true"></i>
        </label>
        <select name="city" class="form-control" id="id_city" data-ajax--url="/autocomplete/cities?slug=" data-ajax--delay="250" data-minimum-input-length="1" data-placeholder="Rechercher un emploi inclusif autour de…"></select>
    </div>
    <div class="input-group ${buttonGroup}">
        <button type="submit" class="btn btn-block btn-ico ${buttonVariant}" aria-label="Rechercher un emploi inclusif">
            <i class="ri-search-line ri-xl fw-bold" aria-hidden="true"></i>
            <span class="me-1">Rechercher</span>
        </button>
    </div>
</div>`,
  id: 'input-group-search',
  metadata: { nestable: true },
}
