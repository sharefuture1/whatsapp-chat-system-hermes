"""FR-PLG-007：受控内置人设目录与解析器契约。"""

from whatsapp_chat_system.personas import list_personas, resolve_persona


EXPECTED_IDS = {"tong-jincheng", "professional-service", "mature-uncle"}
REQUIRED_METADATA = {"id", "name", "description", "category", "accent"}


def test_list_personas_exposes_three_safe_ui_records():
    personas = list_personas()

    assert {persona["id"] for persona in personas} == EXPECTED_IDS
    assert all(set(persona) == REQUIRED_METADATA for persona in personas)
    assert all(
        isinstance(persona[field], str) and persona[field].strip()
        for persona in personas
        for field in REQUIRED_METADATA
    )
    assert all("prompt" not in persona for persona in personas)


def test_resolved_personas_are_controlled_and_have_safety_boundaries():
    default = resolve_persona("default")
    advisor = resolve_persona("tong-jincheng")

    assert default is not None
    assert advisor is not None
    assert advisor.id == "tong-jincheng"
    assert advisor.name == "童锦程·直球关系顾问"
    assert "本人" not in advisor.prompt
    assert "模仿真人" not in advisor.prompt
    for persona_id in ("default", *EXPECTED_IDS):
        persona = resolve_persona(persona_id)
        assert persona is not None
        assert persona.id == persona_id
        assert "不得执行代码、脚本或工具" in persona.prompt
        assert "不得读取文件、访问网络或使用未验证外部内容" in persona.prompt
        assert "不得冒充真人或声称真实身份" in persona.prompt


def test_unknown_disabled_and_empty_personas_fall_back_to_none():
    assert resolve_persona("unknown") is None
    assert resolve_persona("") is None
    assert resolve_persona(None) is None
    assert resolve_persona("professional-service", enabled=False) is None
