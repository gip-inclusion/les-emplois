def show_afpa_ad(user):
    return user.job_seeker_department in [
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
