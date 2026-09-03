from aie_runtime.capabilities import capability_allows, capability_set_attenuates


def test_exact_capability_selector_only_matches_exact_value():
    assert capability_allows("repo.read", "repo.read")
    assert not capability_allows("repo.read", "repo.write")


def test_trailing_star_is_a_prefix_selector_not_general_glob():
    assert capability_allows("mcp.*", "mcp.server.discover")
    assert capability_allows("mcp.tools.call:*", "mcp.tools.call:echo")
    assert not capability_allows("mcp.tools.call:*", "mcp.tools.list")
    assert not capability_allows("mcp.t*ls", "mcp.tools")


def test_child_capability_selectors_must_attenuate_parent_selector():
    assert capability_set_attenuates({"mcp.*"}, {"mcp.tools.call:*", "mcp.resources.list"})
    assert capability_set_attenuates({"mcp.tools.call:*"}, {"mcp.tools.call:echo"})
    assert not capability_set_attenuates({"mcp.tools.call:*"}, {"mcp.resources.list"})
    assert not capability_set_attenuates({"mcp.tools.call:echo"}, {"mcp.tools.call:*"})
