"""Runs a guided journey (see journeys.py) one step at a time.

GET shows the first step. Each POST carries the step index, the navigation (next or previous), the fields of the
current step, and the answers of the other steps as hidden fields. Nothing is kept on the server between steps:
before saving, every form is validated again in full from what the browser sent.
"""

import math

from django.db import transaction
from django.http import QueryDict

from itou.www.next_steps_views.journeys import DEFAULT_SHOW


CONTROL_FIELDS = {"csrfmiddlewaretoken", "step", "nav", "shown"}


def _shown_fields(data):
    return set(data.getlist("shown"))


def _defaults(journey):
    """The initial values the journey gives its forms, field by field."""
    return {
        name: form.get_initial_for_field(field, name)
        for form in journey.build_forms().values()
        for name, field in form.fields.items()
    }


def _display_forms(journey, data):
    """Unbound forms showing what was answered so far, the defaults elsewhere: no error before submitting."""
    if not data:
        return journey.build_forms()
    initial = _defaults(journey)
    shown = _shown_fields(data)
    for form in journey.build_forms(data=data).values():
        for name, field in form.fields.items():
            if name in shown:
                initial[name] = field.widget.value_from_datadict(data, {}, form.add_prefix(name))
    return journey.build_forms(initial=initial)


def _form_keys(step):
    """A step shows one form, several (a tuple of keys), or none."""
    if step.form is None:
        return ()
    return step.form if isinstance(step.form, tuple) else (step.form,)


def _field_names(step, forms):
    """The fields a step renders: its own subset, or every field of its forms, hidden ones included."""
    if step.fields is not None:
        return list(step.fields)
    return [name for key in _form_keys(step) for name in forms[key].fields]


def _step_is_valid(step, bound_forms):
    keys = _form_keys(step)
    if step.fields is None or step.fields == []:
        # Whole forms: a confirmation step checks everything, cross-field rules included.
        return all(bound_forms[key].is_valid() for key in keys)
    form = bound_forms[keys[0]]
    form.is_valid()
    return not any(name in form.errors for name in step.fields)


def _carried(data, rendered):
    return [
        (name, value)
        for name, values in data.lists()
        if name not in CONTROL_FIELDS and name not in rendered
        for value in values
    ]


def run(journey, data):
    """Return the rendering context of the journey after this request, and whether it was completed."""
    data = data if data is not None else QueryDict()
    steps = journey.steps(data)
    index = min(max(int(data.get("step", 0) or 0), 0), len(steps) - 1)
    bound_forms = None
    result = None

    if data:
        if data.get("nav") == "previous":
            index = max(index - 1, 0)
        else:
            bound_forms = journey.build_forms(data=data)
            if _step_is_valid(steps[index], bound_forms):
                # The next steps may depend on this answer.
                steps = journey.steps(data)
                if index < len(steps) - 1:
                    index += 1
                    bound_forms = None
                else:
                    invalid = [i for i, step in enumerate(steps) if not _step_is_valid(step, bound_forms)]
                    if invalid:
                        index = invalid[0]
                    else:
                        with transaction.atomic():
                            result = journey.done(bound_forms)
            elif steps[index].fields == []:
                # A confirmation step found an error in an earlier answer: back to the step that asked for it.
                index = next(
                    (i for i, step in enumerate(steps[:index]) if not _step_is_valid(step, bound_forms)), index
                )

    if result:
        return {"journey": journey, "result": result, "job_seeker": journey.job_seeker}, True

    step = steps[index]
    if bound_forms is None:
        forms = _display_forms(journey, data)
        recap = []
        if step.form and step.fields == []:
            # A confirmation step reads the validated answers.
            validated = journey.build_forms(data=data)
            if all(_step_is_valid(s, validated) for s in steps[:index]):
                recap = journey.recap(validated)
    else:
        forms = bound_forms
        recap = []
    keys = _form_keys(step)
    form = forms[keys[0]] if len(keys) == 1 else None
    field_names = _field_names(step, forms)
    shown = sorted(_shown_fields(data) | set(field_names))
    visible = [name for name in field_names if form and not form.fields[name].widget.is_hidden]
    return {
        "journey": journey,
        "job_seeker": journey.job_seeker,
        "result": None,
        "steps": steps,
        "step": step,
        "step_index": index,
        "step_number": index + 1,
        "is_first_step": index == 0,
        "progress": math.floor((index + 1) / len(steps) * 100),
        "form": form,
        "fields": [form[name] for name in visible],
        # Each visible field with how the step shows it (see journeys.Show).
        "field_rows": [(form[name], step.layout.get(name, DEFAULT_SHOW)) for name in visible],
        "hidden_fields": [form[name] for name in field_names if form and name not in visible],
        "carried": _carried(data, set(field_names)),
        "shown": shown,
        "recap": recap,
        "facts": journey.facts(),
        **journey.context(),
        # A step with several forms names each of them, for templates written for them.
        **{f"form_{key}": forms[key] for key in keys},
    }, False
