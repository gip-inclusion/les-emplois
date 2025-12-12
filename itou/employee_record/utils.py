def is_ntt_required(nir):
    return not nir or nir.startswith(("7", "8"))
