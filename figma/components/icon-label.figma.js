// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=9028-185
// source=les-emplois itou/templates/includes/organizations/phone_li.html (Text) ; itou/templates/includes/organizations/website_li.html (Link) ; itou/templates/includes/copy_to_clipboard.html
// component=Icon + label
const figma = require('figma')
const instance = figma.selectedInstance

const type = instance.getEnum('Type', { Text: 'text', Link: 'link' })
// Hover is CSS; Copied is the "Copié !" tooltip shown by the theme's JS: no markup change.
instance.getEnum('State', { Default: '', Hover: '', Copied: '' })

let example
if (type === 'link') {
  const weblink = instance.getString('Weblink')
  const iconLayer = instance.getInstanceSwap('Icon link')
  const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'global-line'
  example = figma.html`<li>
    <i class="ri-${iconName} fw-normal me-2" aria-hidden="true"></i>
    <a href="https://${weblink}" rel="noopener" target="_blank" class="btn-link fw-medium has-external-link" aria-label="Site web (ouverture dans un nouvel onglet)">${weblink}</a>
</li>`
} else {
  const label = instance.getString('Label')
  const iconLayer = instance.getInstanceSwap('Icon')
  const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'phone-line'
  example = figma.html`<li>
    <i class="ri-${iconName} fw-normal me-2" aria-hidden="true"></i>
    ${label}
    {% include "includes/copy_to_clipboard.html" with content="${label}" css_classes="btn-link fw-medium ms-1" only_icon=True %}
</li>`
}

export default {
  example,
  id: 'icon-label',
  metadata: { nestable: true },
}
