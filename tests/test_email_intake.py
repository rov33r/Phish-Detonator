"""app/email_intake.py: link extraction, red flags, picks (SPEC 11A.6). Model stubbed."""
import pytest

from app import email_intake as ei
from app import llm

KIT = "http://vexalo-docs.203-0-113-5.nip.io/"
EML = f"""From: Vexalo Docs <no-reply@vexalo-share.top>
Reply-To: anna.lindqvist@fjord-mail.com
Subject: Anna shared Q4-budget.pdf with you
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="b1"

--b1
Content-Type: text/plain

Anna shared a file. Open: {KIT}

--b1
Content-Type: text/html

<html><body><p>Anna shared <b>Q4-budget.pdf</b></p>
<a href="{KIT}">https://docs.vexalo.com/q4</a>
<a href="https://vexalo.com/unsubscribe">Unsubscribe</a>
<a href="mailto:help@vexalo.com">Help</a></body></html>
--b1--
"""


@pytest.fixture
def model(monkeypatch):
    script = []

    def fake(messages, schema, *, name, **kw):
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return llm.Reply(item, "main-model")
    monkeypatch.setattr(ei.llm, "chat_json", fake)
    return script


def test_extracts_from_eml_deduplicated_without_mailto():
    links = ei.extract_links(EML)
    assert [link["url"] for link in links] == [KIT, "https://vexalo.com/unsubscribe"]
    assert links[0]["shown_text"] == "https://docs.vexalo.com/q4"


def test_extracts_plain_text_and_strips_punctuation():
    links = ei.extract_links(f"Hi, see {KIT}. Or https://example.com/a?b=1, thanks")
    assert [link["url"] for link in links] == [KIT, "https://example.com/a?b=1"]


def test_extracts_html_only():
    assert ei.extract_links(f'<p>Hi</p><a href="{KIT}">Open</a>')[0] == {"url": KIT, "shown_text": "Open"}


def test_caps_at_ten():
    text = " ".join(f"https://example.com/{i}" for i in range(20))
    assert len(ei.extract_links(text)) == ei.MAX_LINKS


def test_red_flags():
    names = {f["name"] for f in ei.flags(EML)}
    assert names == {"link_text_mismatch", "display_name_mismatch", "reply_to_differs"}


def test_no_flags_on_honest_email():
    honest = ('From: Vexalo <news@vexalo.com>\nSubject: Hi\nContent-Type: text/html\n\n'
              '<a href="https://www.vexalo.com/news">vexalo.com/news</a>')
    assert ei.flags(honest) == []


def test_triage_uses_picks_with_reasons(model):
    model.append({"picks": [{"index": 0, "reason": "I test this because the button says vexalo.com but goes elsewhere."},
                            {"index": 7, "reason": "out of range"}]})
    t = ei.triage(EML)
    assert t["links"][0]["picked"] and "button says" in t["links"][0]["reason"]
    assert not t["links"][1]["picked"] and t["links"][1]["reason"] is None
    assert len(t["flags"]) == 3


def test_triage_falls_back_when_model_down(model):
    model.append(llm.LLMError("down"))
    t = ei.triage(EML)
    assert [link["picked"] for link in t["links"]] == [True, True]
    assert "Planner unavailable" in t["links"][0]["reason"]


def test_triage_without_links_makes_no_call(model):
    assert ei.triage("No links in here.") == {"links": [], "flags": []}


def test_stub_reason_is_replaced(model):
    model.append({"picks": [{"index": 0, "reason": "I test this:"}]})
    assert ei.triage(EML)["links"][0]["reason"].startswith("I test this link because")
