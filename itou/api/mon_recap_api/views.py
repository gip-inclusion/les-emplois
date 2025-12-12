from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED
from rest_framework.views import APIView

from itou.mon_recap.models import NotebookOrder
from itou.utils.auth import LoginNotRequiredMixin


def parse_tally_json(data):
    def array_to_dict(arr):
        res = {}

        for item in arr:
            key = item["key"]
            value = item["value"]
            type = item["type"]
            options = item["options"] if "options" in item else None
            res[key] = {"value": value, "type": type, "options": options}

        return res

    keys = {
        "email": "question_zyQQx0",
        "is_in_priority_department": "question_99JpJV",
        "is_first_order": "question_eQxKxk",
        "is_first_order_in_department": "question_WEpDpv",
        "organization_name": "question_gdNND4",
        "organization_type": "question_VQ11Ly",
        "organization_is_in_network": "question_Edbbk4",
        "organization_network": "question_P1BBde",
        "organization_is_in_qpv_or_zrr": "question_2axxE9",
        "role": "question_Edbbkr",
        "coworkers_will_distribute": "question_rarrjR",
        "coworkers_emails": "question_4JNN4Y",
        "source": "question_G9BBxk",
        "source_details": "question_O4BBDg",
        "kind": "question_Y0zz5J_155db157-3eaa-49a2-a8d1-374e8baeb4b0",
        "unit_price": "question_QeBvBG_6b39eed7-7c47-4a3b-ae89-3772a6f00186",
        "amount": "question_RMBBG9_65c8a739-4a98-4de1-b538-52f752a66ac2",
        "previous_notebooks_out_of_stock": "question_VQxW0j",
        "financing_likelihood": "question_d95E7D",
        "financing_obstacles": "question_Y4LP2z",
        "users_are_autonomous": "question_G9BBxZ",
        "users_need_tools": "question_O4BBDR",
        "users_have_obstacles": "question_VQ11Lg",
        "most_recurring_obstacles": "question_P1BBdV",
        "reason": "question_rOM0QM",
        "amount_wished": "question_xMNNX5",
        "full_name": "question_0BjjQj",
        "address": "question_y2qqPx",
        "siret": "question_O4bNXp",
        "city": "question_XJBBxY",
        "post_code": "question_8app1P",
        "phone_number": "question_5jqqBE",
    }

    res = {}
    res["created_at"] = data["createdAt"]
    fields = array_to_dict(data["data"]["fields"])

    for field, question_key in keys.items():
        value = fields[question_key]["value"]
        type = fields[question_key]["type"]
        options = fields[question_key]["options"]

        if value is None:
            res[field] = None
        elif value is not None and options is None:
            res[field] = value
        else:
            choice = [i for i in options if i["id"] in value]
            if type == "CHECKBOXES":
                res[field] = [i["text"] for i in choice]
            else:
                choice = choice[0]["text"]
                if len(options) == 2:
                    if choice == "Oui":
                        res[field] = True
                        continue
                    elif choice == "Non":
                        res[field] = False
                        continue
                res[field] = choice

    return res


class MonRecapSubmitView(LoginNotRequiredMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        res = parse_tally_json(request.data)
        NotebookOrder.objects.create(**res)
        return Response(status=HTTP_201_CREATED)
