from src.platform.data_onboarding.ask_evidence import format_ask_evidence


def test_format_ask_evidence_objects_not_repr() -> None:
    labels = format_ask_evidence(
        [
            {
                "evidence_id": "ev-1",
                "type": "document_chunk",
                "source_name": "NDA AIR FRANCE.pdf",
                "snippet": "LA EMPRESA: AIR FRANCE PROCESSING CENTER S.A.C.",
            },
            {"type": "document_chunk", "source_name": ""},
            "página 1",
            "  ",
        ]
    )
    joined = " ".join(labels)
    assert "[object Object]" not in joined
    assert "NDA AIR FRANCE.pdf" in labels[0]
    assert "AIR FRANCE PROCESSING CENTER" in labels[0]
    assert "página 1" in labels
    assert all(isinstance(item, str) for item in labels)
