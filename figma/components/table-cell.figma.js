// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8329-31154
// source=les-emplois itou/templates/apply/includes/list_tr.html (text, link, badge, checkbox, action), itou/templates/companies/job_description_list.html (text + icon, switch), itou-theme ItouBadges / ItouInputSelectTextarea stories (badge, input)
// component=Content
const figma = require('figma')
const instance = figma.selectedInstance

// Render a nested instance through its own Code Connect template when it has one.
const nested = (layer) => {
  const child = instance.findInstance(layer)
  return child && child.type === 'INSTANCE' && child.hasCodeConnect() ? child.executeTemplate().example : undefined
}

const text = instance.getString('Text')
const type = instance.getEnum('Type', {
  Text: 'text',
  Badge: 'badge',
  Action: 'action',
  Checkbox: 'checkbox',
  Switch: 'switch',
  'Text badge': 'text-badge',
  'Text link': 'text-link',
  Input: 'input',
  Empty: 'empty',
  'Input hover': 'input',
})
const iconLeft = type === 'text' && instance.getBoolean('Icon left')
const iconRight = type === 'text' && instance.getBoolean('Icon right')
const secondBadge = type === 'badge' && instance.getBoolean('2eme badge')
const iconLayer = iconLeft ? instance.getInstanceSwap('↳ Icon') : undefined
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'map-pin-2-line'
const badge = nested('Badges') || figma.html`<span class="badge badge-sm rounded-pill bg-info text-white">Label</span>`

let example
if (type === 'text' && (iconLeft || iconRight)) {
  example = figma.html`<td>
    <span class="d-flex align-items-center">
        ${iconLeft ? figma.html`<i class="ri-${iconName} me-1" aria-hidden="true"></i>` : ''}
        <span>${text}</span>
        ${iconRight ? figma.html`<i class="ms-1 ri-alert-line" aria-hidden="true"></i>` : ''}
    </span>
</td>`
} else if (type === 'text') {
  example = figma.html`<td>${text}</td>`
} else if (type === 'badge') {
  example = figma.html`<td>
    ${badge}
    ${secondBadge ? badge : ''}
</td>`
} else if (type === 'text-badge') {
  example = figma.html`<td>
    <span class="d-block">${text}</span>
    ${badge}
</td>`
} else if (type === 'text-link') {
  example = figma.html`<td>
    <a class="btn-link" href="#">${text}</a>
</td>`
} else if (type === 'action') {
  example = figma.html`<td class="text-end w-50px align-middle">
    ${nested('Buttons') || figma.html`<a class="btn btn-sm btn-link btn-ico-only" href="#" data-bs-toggle="tooltip" data-bs-title="Voir sa candidature">
        <i class="ri-arrow-drop-right-line fs-lg" aria-label="Voir sa candidature"></i>
    </a>`}
</td>`
} else if (type === 'checkbox') {
  example = figma.html`<th scope="row" class="text-start w-50px">
    <input class="form-check-input" type="checkbox" name="selected-application" value="1" id="select-1" autocomplete="off">
    <label class="visually-hidden" for="select-1">Sélectionner cette candidature</label>
</th>`
} else if (type === 'switch') {
  example = figma.html`<td>
    <div class="form-check form-switch has-state-label">
        <input type="checkbox" class="form-check-input" name="job_description_is_active" id="job_description_is_active_1" checked>
        <label class="form-check-label" for="job_description_is_active_1" data-it-state-label-off="Fermé" data-it-state-label-on="Ouvert"></label>
    </div>
</td>`
} else if (type === 'input') {
  // No editable cell in les-emplois yet: plain small input from itou-theme.
  example = figma.html`<td>
    <input type="text" class="form-control form-control-sm" placeholder="Placeholder" aria-label="${text}">
</td>`
} else {
  example = figma.html`<td></td>`
}

export default {
  example,
  id: 'table-cell',
  metadata: { nestable: true },
}
