import logging
from collections import namedtuple

from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.views.generic import TemplateView

from itou.utils.session import SessionNamespace


logger = logging.getLogger(__name__)


# Compatible with formtools wizard.steps object to share stepper_progress implementation
Steps = namedtuple("Steps", ["current", "step1", "count", "next", "prev"])


class WizardView(TemplateView):
    url_name = None  # Must match the name set in urls.py
    expected_session_kind = None
    steps_config = {}
    template_name = None

    @classmethod
    def initialize_session_and_start(cls, request, reset_url, extra_session_data=None):
        if reset_url is None:
            # This is somewhat extreme but will force developpers to always provide a proper next_url
            raise Http404
        session_data = {
            "config": {
                "reset_url": reset_url,
            },
        }
        if extra_session_data:
            session_data["config"].update(extra_session_data.pop("config", {}))
            session_data.update(extra_session_data)
        session = SessionNamespace.create_uuid_namespace(
            request.session,
            cls.expected_session_kind,
            data=session_data,
        )
        return HttpResponseRedirect(
            reverse(cls.url_name, kwargs={"session_uuid": session.name, "step": list(cls.steps_config)[0]})
        )

    def load_session(self, session_uuid):
        wizard_session = SessionNamespace(self.request.session, self.expected_session_kind, session_uuid)
        # FIXME: It would be great to redirect to a given url (self.failure_redirect_url ?) when there's no session
        # But we need such an url, and to be able to pass the test_func without failure to let dispatch redirect there
        if not wizard_session.exists():
            raise Http404
        # FIXME: Add current_organization.pk in the session and ensure it's still the current_organization
        self.wizard_session = wizard_session
        self.reset_url = wizard_session.get("config", {}).get("reset_url")
        if self.reset_url is None:
            # Session should have been initialized with a reset_url
            raise Http404

    def setup_wizard(self):
        """Additional setup required to load the steps"""
        pass

    def setup(self, request, *args, session_uuid, step, **kwargs):
        super().setup(request, *args, **kwargs)
        self.load_session(session_uuid)

        self.setup_wizard()

        # Check step consistency
        self.steps = self.get_steps()
        if step not in self.steps:
            raise Http404
        self.step = step
        self.next_step = self.get_next_step()

        self.form = self.get_form(self.step, data=self.request.POST if self.request.method == "POST" else None)

    def get_steps(self):
        return list(self.steps_config.keys())

    def get_next_step(self):
        next_step_index = self.steps.index(self.step) + 1
        if next_step_index >= len(self.steps):
            return None
        return self.steps[next_step_index]

    def get_previous_step(self):
        prev_step_index = self.steps.index(self.step) - 1
        if prev_step_index < 0:
            return None
        return self.steps[prev_step_index]

    def get_step_url(self, step):
        return reverse(self.url_name, kwargs={"session_uuid": self.wizard_session.name, "step": step})

    def get_form_initial(self, step):
        return self.wizard_session.get(step, {})

    def get_form_kwargs(self, step):
        return {}

    def get_form_class(self, step):
        return self.steps_config[step]

    def get_form(self, step, data):
        return self.get_form_class(step)(initial=self.get_form_initial(step), data=data, **self.get_form_kwargs(step))

    def find_step_with_invalid_data_until_step(self, step):
        """Return the step with invalid data or None if everything is fine"""
        for previous_step in self.steps:
            if previous_step == step:
                return None
            if self.wizard_session.get(previous_step) is self.wizard_session.NOT_SET:
                return previous_step
            form = self.get_form(previous_step, data=self.wizard_session.get(previous_step, {}))
            if not form.is_valid():
                return previous_step
        return None

    def get(self, request, *args, **kwargs):
        if invalid_step := self.find_step_with_invalid_data_until_step(self.step):
            return HttpResponseRedirect(self.get_step_url(invalid_step))
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.wizard_session.set(self.step, self.form.cleaned_data)
            if self.next_step:
                return HttpResponseRedirect(self.get_step_url(self.next_step))
            else:
                if invalid_step := self.find_step_with_invalid_data_until_step(self.step):
                    messages.warning(request, "Certaines informations sont absentes ou invalides")
                    return HttpResponseRedirect(self.get_step_url(invalid_step))
                success_url = self.done()
                self.wizard_session.delete()
                return HttpResponseRedirect(success_url)
        context = self.get_context_data(**kwargs)
        return self.render_to_response(context)

    def done(self):
        """This is performed just after the last step form is validated."""
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "wizard_steps": Steps(
                current=self.step,
                step1=self.steps.index(self.step) + 1,
                count=len(self.steps),
                next=self.next_step,
                prev=self.get_step_url(self.get_previous_step()) if self.get_previous_step() is not None else None,
            ),
            "form": self.form,
            "reset_url": self.reset_url,
        }
