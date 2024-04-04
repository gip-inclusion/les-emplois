from itou.utils.iterators import chunks


def test_chunks():
    values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

    assert list(chunks(values, 10)) == [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]]
    assert list(chunks(values, 5)) == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    assert list(chunks(values, 2)) == [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]

    assert list(chunks(values, 10, 2)) == [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]]
    assert list(chunks(values, 5, 2)) == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    assert list(chunks(values, 2, 2)) == [[0, 1], [2, 3]]

    assert list(chunks([], 2)) == []
    assert list(chunks([], 2, 2)) == []
