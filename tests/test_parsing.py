from whatsapp_chat_system.parsing import parse_command, parse_incomplete
from whatsapp_chat_system.rewriter import Rewriter


class DummyConfig:
    model = {'model': '', 'base_url': '', 'api_key': ''}


def test_parse_command_colon_form():
    parsed = parse_command('发给 David：起床了吗')
    assert parsed == {'target': 'David', 'message': '起床了吗'}


def test_parse_command_space_form():
    parsed = parse_command('发给 2 起床了吗')
    assert parsed == {'target': '2', 'message': '起床了吗'}


def test_parse_incomplete_command():
    assert parse_incomplete('发给 ເກຍ❤️：') == 'ເກຍ❤️'


def test_translate_only_unknown_keeps_text():
    rewriter = Rewriter(DummyConfig(), lambda *args, **kwargs: None)
    result = rewriter.translate_only({'name': 'David', 'id': 'x'}, '你好', 'Preferred language: unknown')
    assert result.language == 'unchanged'
    assert result.message == '你好'
