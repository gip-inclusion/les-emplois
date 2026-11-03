// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10719-162
// source=itou/templates/components/alerts/alert_global.html ({% component_alert_global %}) + https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-global-alert--docs
// component=Alerte_Site
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
// "New" is the violet .alert-primary ("procédure en cours"): never dismissible, an exit link instead.
const variant = instance.getEnum('Type', { Info: 'info', Warning: 'warning', Danger: 'danger', New: 'primary' })
const hasButton = instance.getBoolean('Button')
const buttonLayer = hasButton ? instance.findInstance('Buttons') : undefined
const buttonLabel = buttonLayer && buttonLayer.type === 'INSTANCE' ? buttonLayer.getString('Text') : "S'inscrire"

let example
if (variant === 'primary') {
  const exitUrl = hasButton ? ' exit_url=exit_url' : ''
  example = figma.html`{% load components %}
{% component_alert_global content=content variant="primary"${exitUrl} %}
    {% fragment as content %}${text}{% endfragment %}
{% endcomponent_alert_global %}`
} else {
  // Global alert story: the action is a link at the end of the message.
  const link = hasButton ? ` <a href="#" class="has-external-link">${buttonLabel}</a>` : ''
  example = figma.html`{% load components %}
{% component_alert_global content=content variant="${variant}" dismissible=True %}
    {% fragment as content %}${text}${link}{% endfragment %}
{% endcomponent_alert_global %}`
}

export default {
  example,
  id: 'site-alert',
  metadata: { nestable: true },
}
