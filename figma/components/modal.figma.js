// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5430-34133
// source=itou-theme story "Modal" (DeleteCommentModal), les-emplois itou/templates/signup/includes/no_email_link.html (illustration), itou/templates/components/alerts/alert.html via {% component_alert %}
// component=Modal
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Titre')
instance.getEnum('Bandeaux infos', { On: true })
const hasAlert = instance.getBoolean('Alerts')
const hasIllustration = instance.getBoolean('Illustration')

const alert = figma.html`{% component_alert title=title content=content variant="warning" extra_classes="mb-3" %}
                    {% fragment as title %}Mobiliser la solution{% endfragment %}
                    {% fragment as content %}<p class="mb-0">…</p>{% endfragment %}
                {% endcomponent_alert %}`
const content = figma.html`<!-- Contenu (slot Content) -->`

export default {
  example: figma.html`<div class="modal fade" id="modal-example" tabindex="-1" aria-labelledby="modal-example-title" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="modal-title" id="modal-example-title">${title}</h3>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fermer"></button>
            </div>
            <div class="modal-body">
                ${hasAlert ? alert : ''}
                ${hasIllustration ? figma.html`<div class="row">
                    <div class="d-none d-md-inline-flex col-md-3">
                        <img src="{% static 'img/no_email.svg' %}" class="img-fluid" alt="">
                    </div>
                    <div class="col-12 col-md-9">
                        ${content}
                    </div>
                </div>` : content}
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-sm btn-outline-primary" data-bs-dismiss="modal">Action 2</button>
                <button type="button" class="btn btn-sm btn-primary">Action 1</button>
            </div>
        </div>
    </div>
</div>`,
  id: 'modal',
  metadata: { nestable: true },
}
