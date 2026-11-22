// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10434-923
// source=les-emplois itou/templates/apply/includes/job_applications_filters/top_filters.html + itou/templates/apply/includes/list_reset_filters.html
// component=Filter
const figma = require('figma')
const instance = figma.selectedInstance

// Render a nested instance through its own Code Connect template when it has one.
const nested = (layer) => {
  const child = instance.findInstance(layer)
  return child && child.type === 'INSTANCE' && child.hasCodeConnect() ? child.executeTemplate().example : undefined
}

const allFilters = instance.getBoolean('Tous les filtres')
const reset = instance.getBoolean('Effacer tout')
const firstFilter =
  nested('Filter') ||
  figma.html`{% include "includes/btn_dropdown_filter/checkboxes.html" with field=filters_form.departments id_suffix="-top" only %}`

export default {
  example: figma.html`<div class="btn-dropdown-filter-group mb-3 mb-md-4">
    ${firstFilter}
    <!-- … un filtre par champ -->
    ${allFilters ? figma.html`<button type="button" class="btn btn-ico btn-dropdown-filter" data-bs-toggle="offcanvas" data-bs-target="#offcanvasApplyFilters" aria-controls="offcanvasApplyFilters">
        <i class="ri-sound-module-fill fw-medium" aria-hidden="true"></i>
        <span>Tous les filtres <span id="all-filters-btn"></span></span>
    </button>` : ''}
    ${reset ? figma.html`<div class="ms-md-auto">
        <a href="?" class="btn btn-ico btn-dropdown-filter" aria-label="Réinitialiser les filtres actifs">
            <i class="ri-eraser-line fw-medium" aria-hidden="true"></i>
            <span>Effacer tout</span>
        </a>
    </div>` : ''}
</div>`,
  id: 'filter-bar',
  metadata: { nestable: true },
}
