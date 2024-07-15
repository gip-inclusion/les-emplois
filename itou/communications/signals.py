from itou.communications.cache import update_active_announcement_cache


def update_cached_announcement_on_model_changes(sender, instance, *args, **kwargs):
    update_active_announcement_cache()
