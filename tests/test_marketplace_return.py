from src.platform.marketplace.return_to import safe_capability_ref, safe_id, safe_return_to


def test_return_to_rejects_external_redirects() -> None:
    assert safe_return_to("/workflows/wf-1") == "/workflows/wf-1"
    assert safe_return_to("/agents/a-1") == "/agents/a-1"
    assert safe_return_to("https://evil.example/workflows") is None
    assert safe_return_to("//evil.example") is None
    assert safe_return_to("/workflows?next=https://evil.example") is None
    assert safe_return_to("javascript:alert(1)") is None
    assert safe_id("../admin") is None
    assert safe_id("n1") == "n1"
    assert safe_capability_ref("payments.checkout.create") == "payments.checkout.create"
    assert safe_capability_ref("https://evil") is None
