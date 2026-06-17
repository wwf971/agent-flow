from __future__ import annotations

from typing import Iterable


RANK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
RANK_WIDTH = 12
RANK_MIN_VALUE = 0
RANK_MAX_VALUE = (len(RANK_ALPHABET) ** RANK_WIDTH) - 1
RANK_MIDDLE_VALUE = RANK_MAX_VALUE // 2
_RANK_CHAR_VALUE_BY_TEXT = {char: index for index, char in enumerate(RANK_ALPHABET)}


def is_lexorank_valid(value: object):
    text = str(value or "")
    if len(text) != RANK_WIDTH:
        return False
    return all(char in _RANK_CHAR_VALUE_BY_TEXT for char in text)


def rank_to_int(rank_text: str):
    if not is_lexorank_valid(rank_text):
        raise ValueError("invalid rank")
    value = 0
    base = len(RANK_ALPHABET)
    for char in rank_text:
        value = value * base + _RANK_CHAR_VALUE_BY_TEXT[char]
    return value


def int_to_rank(value: int):
    value_next = int(value)
    if value_next < RANK_MIN_VALUE or value_next > RANK_MAX_VALUE:
        raise ValueError("rank value out of range")
    base = len(RANK_ALPHABET)
    char_list = []
    for _index in range(RANK_WIDTH):
        value_next, char_index = divmod(value_next, base)
        char_list.append(RANK_ALPHABET[char_index])
    return "".join(reversed(char_list))


def normalize_rank(value: object):
    text = str(value or "")
    return text if is_lexorank_valid(text) else ""


def get_rank_between(rank_before: object = None, rank_after: object = None):
    rank_before_text = normalize_rank(rank_before)
    rank_after_text = normalize_rank(rank_after)
    value_before = rank_to_int(rank_before_text) if rank_before_text else RANK_MIN_VALUE
    value_after = rank_to_int(rank_after_text) if rank_after_text else RANK_MAX_VALUE
    if value_before >= value_after - 1:
        return ""
    return int_to_rank((value_before + value_after) // 2)


def create_rank_list(count: int):
    count_next = max(0, int(count))
    if count_next < 1:
        return []
    step = max(1, RANK_MAX_VALUE // (count_next + 1))
    return [int_to_rank(step * (index + 1)) for index in range(count_next)]


def sort_ranked_items(item_list: Iterable[dict]):
    item_with_index_list = list(enumerate(item_list))
    return [
        item
        for _index, item in sorted(
            item_with_index_list,
            key=lambda entry: (
                0 if is_lexorank_valid(entry[1].get("rankGlobal")) else 1,
                str(entry[1].get("rankGlobal") or "") if is_lexorank_valid(entry[1].get("rankGlobal")) else "",
                entry[0],
            ),
        )
    ]
