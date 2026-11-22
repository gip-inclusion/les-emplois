// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14409-21
// source=les-emplois itou/templates/pro_connect/includes/button.html
// component=ProConnect
const figma = require('figma')
const instance = figma.selectedInstance

// Hover is handled by .proconnect-button:hover (itou/static/css/itou.css): no markup change.
instance.getEnum('State', { Default: 'default', Hover: 'hover' })

export default {
  example: figma.html`{% include "pro_connect/includes/button.html" with login=True %}
<!-- renders: -->
<div class="text-center">
    <a href="{{ pro_connect_url }}" class="proconnect-button" aria-label="Se connecter avec ProConnect"></a>
    <br>
    <a href="https://proconnect.gouv.fr/" class="btn btn-link has-external-link" target="_blank">En savoir plus</a>
</div>`,
  id: 'proconnect',
  metadata: { nestable: true },
}
