from roster import fields


def test_commas():
    assert fields("a,b") == ["a", "b"]
