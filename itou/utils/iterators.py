# Iterator bazaar
# Misc. utils functions related to list processing and iterators


def chunks(lst, n, max_chunk=None):
    """
    Split `lst` in `n` even parts
    """
    for cpt, i in enumerate(range(0, len(lst), n)):
        if max_chunk is not None and cpt >= max_chunk:
            return
        yield lst[i : i + n]
