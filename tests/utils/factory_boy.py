class AutoNowOverrideMixin:
    """This mixin allows you to override fields with `auto_now=True`"""

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        auto_now_desactivated = []
        for field in model_class._meta.get_fields():
            if getattr(field, "auto_now", False) and kwargs.get(field.name):
                field.auto_now = False
                auto_now_desactivated.append(field)
        try:
            return super()._create(model_class, *args, **kwargs)
        finally:
            for field in auto_now_desactivated:
                field.auto_now = True
