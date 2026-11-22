// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10420-15249
// source=les-emplois itou/templates/layout/_organization_switcher_dropdown_menu.html (inside the .dropdown-menu of layout/_organization_switcher_offcanvas.html)
// component=Structure encart
const figma = require('figma')
const instance = figma.selectedInstance

// "Structure switch" tells which of the two organizations is the current one.
const switched = instance.getEnum('Structure switch', { On: false, Off: true })
const first = switched ? '' : ' active'
const second = switched ? ' active' : ''

export default {
  example: figma.html`<div class="dropdown-menu" id="switchOrganizationDropdownMobile">
    <form action="{% url 'dashboard:switch_organization' %}" method="post">
        {% csrf_token %}
        <ul class="list-unstyled">
            <li>
                <button type="submit" class="dropdown-item dropdown-item__summary${first}" name="organization_key" value="company-1">
                    <i class="ri-community-line" aria-hidden="true"></i>
                    <span>ETTI</span>
                    <strong>Une nouvelle chance</strong>
                </button>
            </li>
            <li>
                <button type="submit" class="dropdown-item dropdown-item__summary${second}" name="organization_key" value="company-2">
                    <i class="ri-community-line" aria-hidden="true"></i>
                    <span>AI</span>
                    <strong>Secours emploi</strong>
                </button>
            </li>
        </ul>
    </form>
    <a href="{% url 'companies_views:create_company' %}" class="dropdown-item dropdown-item__summary is-last-sticky">
        <i class="ri-add-line" aria-hidden="true"></i>
        <span>Créer ou rejoindre</span>
        <strong>une nouvelle structure</strong>
    </a>
</div>`,
  id: 'organization-switcher-menu',
  metadata: { nestable: true },
}
