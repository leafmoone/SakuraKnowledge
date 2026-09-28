from sakura_knowledge.mapping import audit_candidates


def test_mapping_character_space_and_no_promotion():
    result = audit_candidates({"1": ["甲", "乙"], "2": [], "3": ["丙"]},
                              {"甲": ["1", "4"], "乙": ["9"], "丙": ["3"]},
                              {"1", "2"}, {"甲", "乙", "丙"})
    assert result["counts"] == {"input": 3, "empty": 1, "one_to_many": 1,
                                "missing": 1, "inconsistent": 1, "many_to_one": 1}
    assert all(c["src"]["namespace"] == "bangumi.character" for c in result["candidates"])
    assert all(c["verification_status"] == "candidate" for c in result["candidates"])
