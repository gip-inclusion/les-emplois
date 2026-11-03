// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=7333-38041
// source=itou/templates/utils/toasts.html (+ https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-toasts--docs)
// component=Toast
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('↳ Title')
const description = instance.getString('Description')
// [toast class (itou_toast_classes), django.contrib.messages function]
const type = instance.getEnum('Type', {
  Error: ['toast--danger', 'error'],
  Success: ['toast--success', 'success'],
  Warning: ['toast--warning', 'warning'],
  Info: ['toast--info', 'info'],
})
const titleOnly = instance.getEnum('Title only', { Off: false, On: true })
const hasIcon = instance.getBoolean('Icon')
const iconLayer = hasIcon ? instance.getInstanceSwap('↳ Icon') : undefined
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'check-line'
const icon = hasIcon
  ? `
        <i class="ri-${iconName} ri-lg me-1" aria-hidden="true"></i>`
  : ''
const buttonLayer = instance.getBoolean('Button') ? instance.findInstance('Buttons') : undefined
const buttonLabel = buttonLayer && buttonLayer.type === 'INSTANCE' ? buttonLayer.getString('Text') : "J'ai compris"
// Button: dismiss button inside the body, from the "Live" story.
const button = buttonLayer
  ? `
        <button class="btn btn-block btn-outline-primary mt-3 d-block d-sm-none" data-bs-dismiss="toast" aria-label="Fermer">${buttonLabel}</button>
    `
  : ''
const body = titleOnly
  ? ''
  : `
    <div class="toast-body">${description}${button}</div>`
// Title and body travel in one message, separated by "||" (itou_toast_title / itou_toast_content).
const message = titleOnly ? title : `${title}||${description}`

export default {
  example: figma.html`{# messages.${type[1]}(request, "${message}", extra_tags="toast") #}
<div class="toast ${type[0]}" role="status" aria-live="assertive" aria-atomic="true" data-bs-delay="6000">
    <div class="toast-header">${icon}
        <strong class="me-auto">${title}</strong>
        <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Fermer">
            <span class="visually-hidden">J'ai compris</span>
        </button>
    </div>${body}
</div>`,
  id: 'toast',
  metadata: { nestable: true },
}
