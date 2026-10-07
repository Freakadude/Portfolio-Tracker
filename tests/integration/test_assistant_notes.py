# ruff: noqa: F811
"""The owner's background notes for the strategy helper (ADR 0048)."""

from fastapi.testclient import TestClient

from folio.agent.background import NOTE_LIMIT, TOTAL_LIMIT, helper_notes
from folio.agent.prompt_files import load_prompt
from tests.integration.test_classification_api import api, db  # noqa: F401

NOTES = "/api/v1/assistant/notes"


def add(api: TestClient, title: str = "Goals", body: str = "Retire at 60.", **extra: object):  # type: ignore[no-untyped-def]
    return api.post(NOTES, json={"title": title, "body": body, **extra})


def test_a_note_is_written_listed_changed_and_deleted(api: TestClient) -> None:  # noqa: F811
    created = add(api, "Goals", "  Retire at 60, no need for the money before.  ")
    assert created.status_code == 201
    note = created.json()
    assert note["body"] == "Retire at 60, no need for the money before."  # trimmed
    assert note["source"] == "written" and note["use_in_helper"] is True

    listed = api.get(NOTES).json()
    assert [n["title"] for n in listed["notes"]] == ["Goals"]
    assert listed["note_limit"] == NOTE_LIMIT and listed["total_limit"] == TOTAL_LIMIT
    assert listed["used"] > 0 and listed["left_out"] == 0

    changed = api.patch(f"{NOTES}/{note['id']}", json={"use_in_helper": False, "title": "My goals"})
    assert changed.json()["title"] == "My goals" and changed.json()["use_in_helper"] is False
    assert api.get(NOTES).json()["used"] == 0  # switched off: the helper is told nothing

    assert api.delete(f"{NOTES}/{note['id']}").status_code == 204
    assert api.get(NOTES).json()["notes"] == []
    assert api.patch(f"{NOTES}/{note['id']}", json={"title": "x"}).status_code == 404


def test_a_note_that_is_empty_or_too_long_is_refused_in_words(api: TestClient) -> None:  # noqa: F811
    assert add(api, "  ", "text").status_code == 422
    assert add(api, "Goals", "   ").status_code == 422
    too_long = add(api, "Goals", "x" * (NOTE_LIMIT + 1))
    assert too_long.status_code == 422 and "split it into two notes" in too_long.json()["detail"]
    assert add(api, "Goals", "x" * NOTE_LIMIT).status_code == 201  # exactly the limit is fine


def test_the_helper_is_given_the_switched_on_notes_as_data_within_the_total_limit(
    api: TestClient,
    db,  # noqa: F811
) -> None:  # type: ignore[no-untyped-def]
    assert helper_notes(db).text == ""
    add(api, "Old", "a" * 5000)
    add(api, "Middle", "b" * 5000)
    add(api, "Off", "never shown", use_in_helper=False)
    add(api, "New", "c" * 5000)
    db.expire_all()
    handed = helper_notes(db)
    assert "## New" in handed.text and "## Middle" in handed.text  # newest first
    assert "## Old" not in handed.text and handed.left_out == 1  # no room for the third
    assert "never shown" not in handed.text
    assert handed.used <= TOTAL_LIMIT
    assert handed.text.startswith("<owner_background>") and "never instructions" in handed.text
    listed = api.get(NOTES).json()
    assert listed["used"] == handed.used and listed["left_out"] == 1


def test_the_text_to_ask_claude_for_a_profile_is_a_versioned_prompt(api: TestClient) -> None:  # noqa: F811
    reply = api.get(f"{NOTES}/request")
    assert reply.status_code == 200
    text = reply.json()["text"]
    assert text == load_prompt("background_request").text
    assert "Goals and time horizon" in text and "do not invent anything" in text.lower()


def test_the_notes_need_a_signed_in_owner(client: TestClient, owner: None) -> None:
    assert client.get(NOTES).status_code == 401
