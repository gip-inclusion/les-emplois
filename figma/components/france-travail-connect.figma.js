// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=9262-528
// source=les-emplois itou/templates/signup/includes/ft_connect_button.html
// component=France Travail Connect
const figma = require('figma')
const instance = figma.selectedInstance

// "Nom2" is a faded duplicate in the kit with no counterpart in code: same markup.
instance.getEnum('Nom', { 'France Travail': 'default', Nom2: 'default' })

export default {
  example: figma.html`{% include "signup/includes/ft_connect_button.html" %}
<!-- renders: -->
<form method="post" action="{% url 'ft_connect:authorize' %}">
    {% csrf_token %}
    <input type="image" src="{% static 'img/ft_connect_btn.svg' %}" alt="Se connecter avec votre compte France Travail">
</form>`,
  id: 'france-travail-connect',
  metadata: { nestable: true },
}
