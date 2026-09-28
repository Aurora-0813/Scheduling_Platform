"""
LLM 输出解析容错的六级容错逐级覆盖
"""
from __future__ import annotations

from app.agent.chains.json_utils import (
    coerce_content,
    looks_like_prose,
    parse_llm_json,
)

VALID = {"title": "标题", "content": "正文"}


def test_level1_direct_json():
    assert parse_llm_json('{"title": "标题", "content": "正文"}') == VALID


def test_level2_markdown_fence():
    text = '```json\n{"title": "标题", "content": "正文"}\n```'
    assert parse_llm_json(text) == VALID


def test_level2_fence_without_language_tag():
    text = '```\n{"title": "标题", "content": "正文"}\n```'
    assert parse_llm_json(text) == VALID


def test_level3_surrounded_by_chatter():
    text = '好的，这是为您生成的文案：{"title": "标题", "content": "正文"} 希望对您有帮助。'
    assert parse_llm_json(text) == VALID


def test_level4_python_literal_single_quotes():
    text = "{'title': '标题', 'content': '正文'}"
    assert parse_llm_json(text) == VALID


def test_level5_regex_rescue():
    """
    JSON 与 Python 字面量都解析不了，但两个字段仍是带引号的字符串。
    正文里混入未加引号的裸值，确保前四级都会失败。
    """
    text = '{\n  "title": "抢修通知",\n  "content": "需要现场处理",\n  "note": 未加引号的裸值\n}'
    rescued = parse_llm_json(text)
    assert rescued == {"title": "抢修通知", "content": "需要现场处理"}


def test_level5_requires_both_fields():
    """只抢救出 title 而没有 content 时应当放弃，避免半个结果污染通知"""
    text = '{"title": "只有标题", "note": 裸值}'
    assert parse_llm_json(text) is None


def test_level6_gives_up():
    assert parse_llm_json("这是一段完全不含 JSON 结构的自然语言文本内容。") is None


def test_empty_input():
    assert parse_llm_json("") is None
    assert parse_llm_json("   ") is None


def test_array_wrapped_object_is_rescued():
    """
    模型偶尔会多包一层数组。第三级「截取首末花括号」会把里面的对象捞出来，
    这是刻意保留的容错：结果仍是 dict，下游按字段取值不会出错。
    """
    assert parse_llm_json('[{"title": "标题", "content": "正文"}]') == VALID


def test_array_without_the_two_fields_still_fails():
    """数组里没有可用字段时仍应放弃，不得返回半个结果"""
    assert parse_llm_json('[{"foo": "bar"}, {"baz": 1}]') is None


def test_escaped_characters_survive_rescue():
    text = '{"title": "换行\\n标题", "content": "正文", "note": 裸值}'
    rescued = parse_llm_json(text)
    assert rescued is not None
    assert "\n" in rescued["title"]


# ---------- coerce_content ----------


def test_coerce_content_plain_string():
    assert coerce_content("abc") == "abc"


def test_coerce_content_multimodal_blocks():
    """langchain-openai 1.x 的 content 可能是分段列表，不能直接 .strip()"""
    blocks = [{"type": "text", "text": "前半"}, {"type": "text", "text": "后半"}]
    assert coerce_content(blocks) == "前半后半"


def test_coerce_content_mixed_and_none():
    assert coerce_content(None) == ""
    assert coerce_content([{"type": "text", "text": "abc"}]) == "abc"
    assert coerce_content([]) == ""


# ---------- looks_like_prose ----------


def test_looks_like_prose_accepts_sentences():
    assert looks_like_prose("您好，您预约的场地即将开始使用，请提前到场。")


def test_looks_like_prose_rejects_json_and_short_text():
    assert not looks_like_prose('{"title": "标题"}')
    assert not looks_like_prose("太短")
    assert not looks_like_prose("")
