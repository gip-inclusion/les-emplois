# Iterator bazaar
# Misc. utils functions related to list processing and iterators


def chunks(lst, n):
    """
    Split `lst` in `n` even parts
    """
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
