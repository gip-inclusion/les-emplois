from allauth.account.forms import LoginForm


class ItouLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs["placeholder"] = "**********"
        self.fields["login"].widget.attrs["placeholder"] = "adresse@email.fr"
        self.fields["login"].label = "Adresse e-mail"
