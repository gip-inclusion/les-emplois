import json


def hx_trigger_modal_control(modal_id, action):
    return {"HX-Trigger": json.dumps({"modalControl": {"id": modal_id, "action": action}})}
