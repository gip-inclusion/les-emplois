def show_afpa_ad(user):
    postcode = user.jobseeker_profile.hexa_post_code or user.post_code
    return postcode[:2] in [
        # Hauts-de-france
        "02",
        "59",
        "60",
        "62",
        "80",
        # Nouvelle aquitaine
        "16",
        "17",
        "19",
        "23",
        "24",
        "33",
        "40",
        "47",
        "64",
        "79",
        "86",
        "87",
    ]
