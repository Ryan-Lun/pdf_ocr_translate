from app.services import submit_quota


def test_normalize_submitter_key_prefers_creator_name():
    assert (
        submit_quota.normalize_submitter_key(" Alice 01 ", "10.0.0.1")
        == "creator:alice 01"
    )


def test_normalize_submitter_key_falls_back_to_ip():
    assert submit_quota.normalize_submitter_key("", "10.0.0.1") == "ip:10.0.0.1"
