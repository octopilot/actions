from common.notes import DEFAULT_TEMPLATE, bare_version


def test_a_tag_style_version_is_not_prefixed_twice():
    assert bare_version("v0.1.220") == "0.1.220"
    assert bare_version("V1.2.3") == "1.2.3"
    assert DEFAULT_TEMPLATE.replace("{{VERSION}}", bare_version("v0.1.220")).startswith("# Release v0.1.220")


def test_a_bare_version_is_left_alone():
    assert bare_version("0.1.220") == "0.1.220"
    assert bare_version("vnext") == "vnext"
