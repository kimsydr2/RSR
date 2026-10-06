from cadet_tracker.sheet import classify, parse_grid, MISSING, ATTENDING, NOT_ATTENDING, LATE, SEE_OTHER, OTHER

COLS = {"rank": "Rank", "last": "Last Name", "first": "First Name"}


def test_classify():
    assert classify("").status == MISSING
    assert classify(None).status == MISSING
    assert classify("  Yes ").status == ATTENDING
    r = classify("No, ROC prep")
    assert r.status == NOT_ATTENDING and r.reason == "ROC prep"
    assert classify("no SIQ").reason == "SIQ"
    assert classify("Late, class").status == LATE
    assert classify("like ethan").status == SEE_OTHER
    assert classify("Honor").status == OTHER and classify("Honor").responded


def test_parse_grid_groups_roles_and_skips_headers():
    rows = [
        ["title row"],
        ["", "Rank", "Last Name", "First Name", "Monday"],
        ["Freshman Platoon"],
        ["SL", "C/SSG", "Reed", "Jordan", "yes"],
        ["", "NC/", "Cole", "Taylor", ""],
        ["", "", "", "", ""],
    ]
    out = parse_grid(rows, COLS, ["Monday"])
    assert [c.name for c in out] == ["Reed, Jordan", "Cole, Taylor"]
    assert out[0].role == "SL" and out[1].group == "Freshman Platoon"
    assert out[1].responses["Monday"].status == MISSING
