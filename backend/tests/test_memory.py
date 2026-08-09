from app.memory import RetrievedMemory, format_memory_context, parse_extracted_facts


def test_parse_extracted_facts_plain_array():
    raw = '["The user\'s dog is named Biscuit.", "The user works remotely on Fridays."]'
    assert parse_extracted_facts(raw) == [
        "The user's dog is named Biscuit.",
        "The user works remotely on Fridays.",
    ]


def test_parse_extracted_facts_empty_array():
    assert parse_extracted_facts("[]") == []


def test_parse_extracted_facts_wrapped_in_prose():
    raw = 'Sure, here are the facts:\n["The user prefers morning meetings."]\nLet me know if needed.'
    assert parse_extracted_facts(raw) == ["The user prefers morning meetings."]


def test_parse_extracted_facts_wrapped_in_code_fence():
    raw = '```json\n["The user\'s anniversary is June 12th."]\n```'
    assert parse_extracted_facts(raw) == ["The user's anniversary is June 12th."]


def test_parse_extracted_facts_no_brackets_returns_empty():
    assert parse_extracted_facts("There's nothing worth remembering here.") == []


def test_parse_extracted_facts_invalid_json_returns_empty():
    assert parse_extracted_facts("[not valid json,,,]") == []


def test_parse_extracted_facts_no_array_present_returns_empty():
    assert parse_extracted_facts('{"fact": "not an array"}') == []


def test_parse_extracted_facts_drops_blank_entries():
    raw = '["The user likes tea.", "  ", ""]'
    assert parse_extracted_facts(raw) == ["The user likes tea."]


def test_format_memory_context_renders_bulleted_facts():
    memories = [
        RetrievedMemory(id=1, content="The user's dog is named Biscuit.", distance=0.01),
        RetrievedMemory(id=2, content="The user works remotely on Fridays.", distance=0.05),
    ]
    context = format_memory_context(memories)
    assert "- The user's dog is named Biscuit." in context
    assert "- The user works remotely on Fridays." in context
