// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10434-895
// source=les-emplois itou/templates/includes/btn_dropdown_filter/checkboxes.html, itou/templates/apply/includes/job_applications_filters/top_filters.html ("Tous les filtres"), itou/static/js/htmx_dropdown_filter.js (.has-selected-item, counter)
// component=Filter
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const count = instance.getString('Count')
// Hover is handled by CSS only.
instance.getEnum('Hover', { Off: '', On: '' })
const filled = instance.getEnum('Filled', { Off: false, On: true })
const open = instance.getEnum('Open', { Off: false, On: true })
const allFilters = instance.getEnum('Tous les filtres', { Off: false, On: true })

let example
if (allFilters) {
  // The counter is filled in by htmx_dropdown_filter.js, e.g. " (2)".
  example = figma.html`<button type="button" class="btn btn-ico btn-dropdown-filter" data-bs-toggle="offcanvas" data-bs-target="#offcanvasApplyFilters" aria-controls="offcanvasApplyFilters">
    <i class="ri-sound-module-fill fw-medium" aria-hidden="true"></i>
    <span>Tous les filtres <span id="all-filters-btn">${filled ? ` ${count}` : ''}</span></span>
</button>`
} else {
  example = figma.html`<div class="dropdown">
    <button type="button" class="btn btn-dropdown-filter dropdown-toggle${filled ? ' has-selected-item' : ''}${open ? ' show' : ''}" data-bs-toggle="dropdown" data-bs-display="static" data-bs-auto-close="outside" aria-expanded="${open ? 'true' : 'false'}">
        ${text}
    </button>
    <ul class="dropdown-menu${open ? ' show' : ''}">
        <li class="dropdown-item">
            <div class="form-check">
                <input id="id_departments_0-top" class="form-check-input" name="departments" type="checkbox" value="90"${filled ? ' checked' : ''}>
                <label for="id_departments_0-top" class="form-check-label">90 - Territoire de Belfort</label>
            </div>
        </li>
    </ul>
</div>`
}

export default {
  example,
  id: 'filter-button',
  metadata: { nestable: true },
}
