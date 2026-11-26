from eval.score import keys_for, score_run

SUBJ = {"subject_id": "s", "records": [
    {"key": "k1", "url": "https://archive.org/details/twelfthregimentc00conn", "tier": "T1", "host": "archive.org"},
    {"key": "k2", "url": "https://www.loc.gov/resource/sn92051392/1920-06-18/ed-1/?sp=13", "tier": "T1", "host": "loc.gov"},
    {"key": "k3", "url": None, "tier": "T3", "host": "private"}]}


def test_ia_page_url_matches_the_book():
    assert keys_for("https://archive.org/details/twelfthregimentc00conn/page/n13/mode/1up?q=Burnham") & keys_for(SUBJ["records"][0]["url"])


def test_loc_page_param_ignored():
    assert keys_for("https://www.loc.gov/resource/sn92051392/1920-06-18/ed-1/?sp=2&q=x") & keys_for(SUBJ["records"][1]["url"])


def test_candidates_are_not_verified_without_labels():
    run = {"run_id": "r", "agent": "B5", "budget": 50, "citations": [
        {"url": "https://archive.org/details/twelfthregimentc00conn/page/n13", "depth": 2, "node": "r3.2"}]}
    s = score_run(run, SUBJ, {})
    assert s["candidate_hits"] == 1 and s["hit_depths"] == [2]
    assert s["verified_recall"] is None and "candidate only" in s["label_status"]
