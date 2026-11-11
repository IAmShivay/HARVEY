import pytest
from types import SimpleNamespace

from harvey.config import ServiceOffer
from harvey.service_match import build_prompt, parse_pick, services_of

SERVICES = [
    ServiceOffer(name="Product finder", solves="shoppers unsure which product fits",
                 first_project="quiz on the product pages"),
    ServiceOffer(name="AI support agent", solves="inbox full of order questions"),
]


def test_pick_must_name_a_listed_service():
    pick = parse_pick({"service": "product finder", "why": "unsure buyers",
                       "loom_points": ["a", "b", "c", "d"]}, SERVICES)
    assert pick["service"] == "Product finder"
    assert pick["first_project"] == "quiz on the product pages"
    assert pick["loom_points"] == ["a", "b", "c"]


def test_unknown_or_malformed_pick_is_dropped():
    assert parse_pick({"service": "Full rebrand"}, SERVICES) is None
    assert parse_pick(["Product finder"], SERVICES) is None
    assert parse_pick(None, SERVICES) is None


def test_prompt_lists_services_and_says_internal():
    prompt = build_prompt(SERVICES, "Ceptics", "", [{"subject": "plug", "body": "Hi there"}])
    assert "Product finder: fixes shoppers unsure which product fits" in prompt
    assert "never sent" in prompt


def test_no_services_configured_means_off():
    assert services_of(SimpleNamespace(product=SimpleNamespace(services=[]))) == []
    assert services_of(SimpleNamespace()) == []


def test_prompt_marks_email_one_as_the_leads_own():
    prompt = build_prompt(SERVICES, "Marianella", "",
                          [{"subject": "batch", "body": "sold out"}, {"subject": "builder", "body": "configurator"}])
    assert "Email 1 (written for this lead) - batch" in prompt
    assert "Follow-up 1 - builder" in prompt
    assert "don't pick a service just because a follow-up mentions it" in prompt


@pytest.mark.asyncio
async def test_lead_emails_in_step_order_with_template_fill(tmp_path):
    from harvey.models.campaign import EmailStep
    from harvey.service_match import lead_emails
    from harvey.state import StateManager

    state = StateManager(str(tmp_path / "h.db"))
    await state.init_db()
    async with state._connect() as db:
        for step, created in ((2, "2026-01-02"), (1, "2026-01-03")):
            await db.execute(
                "INSERT INTO outbox (id, campaign_id, prospect_id, step, kind, to_email, subject, body, status, created_at) "
                "VALUES (?, 'c1', 'p1', ?, 'sequence', 'a@b.co', ?, ?, 'pending_review', ?)",
                (f"o{step}", step, f"s{step}", f"b{step}", created))
        await db.commit()
    template = [EmailStep(step=3, subject="s3", body="b3", delay_days=4)]
    emails = await lead_emails(state, "p1", template)
    assert [e["subject"] for e in emails] == ["s1", "s2", "s3"]
