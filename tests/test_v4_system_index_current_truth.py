from scripts import validate_private_control_v4 as validator


def test_reviewed_system_index_is_current_post_live_contract():
    assert validator.REVIEWED_SYSTEM_INDEX_BLOB_SHA == "4c4587d1dfab06d5cbecd28da047c496f698207e"
