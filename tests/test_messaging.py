from whatsapp_chat_system.messaging import resolve_target


class DummyResult:
    pass


def test_resolve_target_alias():
    aliases = {'2': {'chat_id': 'abc@lid', 'name': 'David', 'type': 'dm'}}
    assert resolve_target('2', [], aliases)['id'] == 'abc@lid'


def test_resolve_target_by_name():
    targets = [{'id': 'xyz@lid', 'name': 'ເກຍ❤️', 'type': 'dm'}]
    resolved = resolve_target('ເກຍ', targets, {})
    assert resolved['id'] == 'xyz@lid'
