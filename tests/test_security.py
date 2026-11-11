from mathfacts import security


def test_long_phrase_is_accepted(app):
    with app.app_context():
        assert security.password_problems("correct horse battery") == []


def test_short_password_is_refused(app):
    with app.app_context():
        problems = security.password_problems("short1")
        assert any("at least 10" in p for p in problems)


def test_common_password_is_refused_in_any_case(app):
    with app.app_context():
        assert security.password_problems("PASSWORD1234")


def test_password_matching_username_or_email_is_refused(app):
    with app.app_context():
        assert security.password_problems(
            "kimsmithfamily", username="KimSmithFamily", email="x@example.com"
        )
        assert security.password_problems(
            "kim@example.com", username="kim", email="KIM@example.com"
        )


def test_hash_verifies_and_rejects_wrong_password(app):
    with app.app_context():
        stored = security.hash_password("correct horse battery")
        assert security.verify_password(stored, "correct horse battery") == (True, False)
        assert security.verify_password(stored, "wrong horse battery") == (False, False)


def test_corrupt_hash_does_not_raise(app):
    with app.app_context():
        assert security.verify_password("not-a-hash", "anything") == (False, False)


def test_name_rules():
    assert security.name_problem("Kevin") is None
    assert security.name_problem("Mary Ann") is None
    assert security.name_problem("") is not None
    assert security.name_problem("x" * 61) is not None


def test_email_and_username_rules():
    assert security.valid_email("kim@example.com")
    assert not security.valid_email("kim@@example")
    assert security.valid_username("kim.smith-2")
    assert not security.valid_username("ab")
    assert not security.valid_username("kim smith")


def test_tokens_are_unique_and_url_safe():
    a, b = security.new_token(), security.new_token()
    assert a != b
    assert len(a) >= 40
    assert all(ch.isalnum() or ch in "-_" for ch in a)
