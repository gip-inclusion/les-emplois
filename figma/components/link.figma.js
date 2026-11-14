// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=6419-39883
// source=les-emplois itou/templates/apply/includes/job_application_external_transfer_progress.html (btn-link btn-ico) ; itou/templates/includes/organizations/website_li.html (has-external-link) ; itou/templates/includes/pagination.html (aria-disabled)
// component=Link
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const iconPosition = instance.getEnum('Icon', { Off: 'off', Left: 'left', Right: 'right' })
const disabled = instance.getEnum('State', { Default: '', Hover: '', Focus: '', Disabled: ' disabled' })
const disabledAttrs = disabled ? ' tabindex="-1" aria-disabled="true"' : ''
const iconLayer = iconPosition === 'off' ? undefined : instance.getInstanceSwap('Icon type')
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'external-link-line'
const icon = `<i class="ri-${iconName}" aria-hidden="true"></i>`

let example
if (iconPosition === 'right' && iconName === 'external-link-line') {
  // External links: the theme draws the icon itself via .has-external-link::after.
  example = figma.html`<a href="#" class="btn-link has-external-link${disabled}" target="_blank" rel="noopener"${disabledAttrs}>${text}</a>`
} else if (iconPosition === 'left') {
  example = figma.html`<a href="#" class="btn-link btn-ico${disabled}"${disabledAttrs}>
    ${icon}
    <span>${text}</span>
</a>`
} else if (iconPosition === 'right') {
  example = figma.html`<a href="#" class="btn-link btn-ico${disabled}"${disabledAttrs}>
    <span>${text}</span>
    ${icon}
</a>`
} else {
  example = figma.html`<a href="#" class="btn-link${disabled}"${disabledAttrs}>${text}</a>`
}

export default {
  example,
  id: 'link',
  metadata: { nestable: true },
}
