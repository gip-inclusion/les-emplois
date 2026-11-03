// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=6974-35084
// source=itou/templates/components/alerts/alert.html ({% component_alert %}; call_to_action as in itou/templates/dashboard/dashboard.html)
// component=Alerts
const figma = require('figma')
const instance = figma.selectedInstance

const description = instance.getString('Description')
const hasTitle = instance.getBoolean('Title')
const title = hasTitle ? instance.getString('↳ Title') : ''
const variant = instance.getEnum("Type de d'alerte", {
  Info: 'info',
  Success: 'success',
  Warning: 'warning',
  Danger: 'danger',
  Important: 'important',
})
// Icons the component renders when no custom_icon is given.
const defaultIcons = {
  info: 'information-line',
  success: 'checkbox-circle-line',
  warning: 'error-warning-line',
  danger: 'close-circle-line',
  important: 'alert-line',
}
const iconLayer = instance.getInstanceSwap('Icon')
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : defaultIcons[variant]
const customIcon = iconName === defaultIcons[variant] ? '' : ` custom_icon="ri-${iconName}"`
const dismissible = instance.getBoolean('Close') ? ' dismissible=True' : ''
const buttonClass = instance.getEnum('Button type', { Primary: 'btn-primary', Ghost: 'btn-link' })
const hasButton = instance.getBoolean('Button')
const buttonLayer = hasButton ? instance.findInstance('Buttons') : undefined
const buttonLabel = buttonLayer && buttonLayer.type === 'INSTANCE' ? buttonLayer.getString('Text') : 'Mettre à jour'

const titleArg = hasTitle ? ' title=title' : ''
const ctaArg = hasButton ? ' call_to_action=call_to_action' : ''
const titleFragment = hasTitle
  ? `
    {% fragment as title %}${title}{% endfragment %}`
  : ''
const ctaFragment = hasButton
  ? `
    {% fragment as call_to_action %}
        <a class="btn btn-sm ${buttonClass}" href="#">${buttonLabel}</a>
    {% endfragment %}`
  : ''

export default {
  example: figma.html`{% load components %}
{% component_alert${titleArg} content=content${ctaArg} variant="${variant}"${dismissible}${customIcon} %}${titleFragment}
    {% fragment as content %}
        <p class="mb-0">${description}</p>
    {% endfragment %}${ctaFragment}
{% endcomponent_alert %}`,
  id: 'alerts',
  metadata: { nestable: true },
}
