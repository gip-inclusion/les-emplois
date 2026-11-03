// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=11200-2176
// source=les-emplois itou/templates/apply/includes/job_applications_filters/offcanvas.html + offcanvas_footer.html + list_reset_filters.html
// component=Filter_Pannel
const figma = require('figma')
const instance = figma.selectedInstance

// Render a nested instance through its own Code Connect template when it has one.
const nested = (layer) => {
  const child = instance.findInstance(layer)
  return child && child.type === 'INSTANCE' && child.hasCodeConnect() ? child.executeTemplate().example : undefined
}

const title = instance.getString('Title')
const hasIcon = instance.getBoolean('Icon')
const iconLayer = hasIcon ? instance.getInstanceSwap('↳ Icon') : undefined
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'sound-module-fill'
const hasFooter = instance.getBoolean('Button')
const hasReset = hasFooter && instance.getBoolean('+ Button')
const item = nested('Item_Filter_Pannel') || figma.html`{% include "includes/field_collapse_checkbox.html" with field=filters_form.departments only %}`

export default {
  example: figma.html`<div class="c-offcanvas-filters offcanvas offcanvas-end" tabindex="-1" aria-labelledby="offcanvasApplyFiltersLabel" id="offcanvasApplyFilters">
    <div class="offcanvas-header">
        <h4 class="mb-0${hasIcon ? ' btn-ico' : ''}" id="offcanvasApplyFiltersLabel">
            ${hasIcon ? figma.html`<i class="ri-${iconName} fw-medium" aria-hidden="true"></i>` : ''}
            <span>${title}</span>
        </h4>
        <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Fermer"></button>
    </div>
    <div class="offcanvas-body" id="offcanvasApplyFiltersContent">
        ${item}
        <!-- … un bloc par filtre -->
    </div>
    ${hasFooter ? figma.html`<div class="offcanvas-footer gap-3" id="offcanvasApplyFiltersButtons">
        <button type="button" data-bs-dismiss="offcanvas" class="btn btn-block btn-primary">Voir</button>
        ${hasReset ? figma.html`<a href="?" class="btn btn-ico btn-block btn-outline-primary" aria-label="Réinitialiser les filtres actifs">
            <i class="ri-eraser-line fw-medium" aria-hidden="true"></i>
            <span>Effacer tout</span>
        </a>` : ''}
    </div>` : ''}
</div>`,
  id: 'filter-panel',
  metadata: { nestable: true },
}
