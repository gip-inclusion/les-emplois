from django import forms

from itou.employee_record.models import EmployeeRecord


# The user is only able to select a subset of the possible
# employee record statuses.
# The other ones are internal only.
_statuses = [
    EmployeeRecord.Status.NEW,
    EmployeeRecord.Status.SENT,
    EmployeeRecord.Status.REJECTED,
    EmployeeRecord.Status.PROCESSED,
]


class SelectEmployeeRecordStatusForm(forms.Form):

    _choices = [(choice.name, choice.label) for choice in _statuses]
    status = forms.ChoiceField(
        widget=forms.RadioSelect(),
        choices=_choices,
        initial=EmployeeRecord.Status.NEW,
    )
