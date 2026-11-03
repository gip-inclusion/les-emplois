// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=2698-5793
// source=les-emplois itou/templates/signup/includes/france_connect_button.html
// component=France Connect
const figma = require('figma')
const instance = figma.selectedInstance

// BleuClair is the :hover look of .itou-france-connect (itou/static/css/itou.css): no markup change.
instance.getEnum('Couleur', { BleuFoncé: 'default', BleuClair: 'hover' })

export default {
  example: figma.html`{% include "signup/includes/france_connect_button.html" %}
<!-- renders: -->
<div class="text-center">
    <a href="{% url 'france_connect:authorize' %}" aria-label="S'identifier avec FranceConnect">
        <img class="img-fluid mb-1 itou-france-connect" alt="">
    </a>
    <br>
    <a class="btn btn-link has-external-link" href="https://franceconnect.gouv.fr/">Qu’est-ce que FranceConnect ?</a>
</div>`,
  id: 'france-connect',
  metadata: { nestable: true },
}
