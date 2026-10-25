"""normalize_profile 的规范化口径（纯逻辑，不需要数据库）。

覆盖 6 种真机脏写法 + 2 组「不应相等」的反例：
1. 大小写        `Pixel 7 Pro` / `PIXEL 7 PRO`
2. 多余空格      `  Pixel   7   Pro  `
3. Android 13 vs android-13
4. 1080*2400 vs 1080x2400
5. 分辨率竖写    2400x1080
6. 版本尾零      13.0.0 / 13.0
反例 A：系统版本不同（android-13 vs android-14）
反例 B：机型不同（pixel-7-pro vs pixel-8-pro）
"""

from __future__ import annotations

import pytest

from app.domain.profiles import (
    ProfileNormalizationError,
    normalize_profile,
    profile_components,
    profiles_comparable,
)

# ---------------------------------------------------------------------------
# 6 种脏写法 -> 同一个规范形
# ---------------------------------------------------------------------------


def test_normalize_is_case_insensitive():
    """脏写法 1：大小写。"""
    assert (
        normalize_profile({"os": "ANDROID", "os_version": "13", "resolution": "1080x2400", "model": "PIXEL 7 PRO"})
        == "android-13|1080x2400|pixel-7-pro"
    )


def test_normalize_collapses_extra_whitespace():
    """脏写法 2：多余空格（含全角空格与制表符）。"""
    assert (
        normalize_profile(
            {"os": " Android ", "os_version": " 13 ", "resolution": " 1080 x 2400 ", "model": "  Pixel   7\tPro  "}
        )
        == "android-13|1080x2400|pixel-7-pro"
    )


def test_normalize_android_13_matches_dash_form():
    """脏写法 3：`Android 13` 与 `android-13` 必须等价。"""
    spaced = normalize_profile("Android 13|1080x2400|Pixel 7 Pro")
    dashed = normalize_profile("android-13|1080x2400|pixel-7-pro")
    assert spaced == dashed == "android-13|1080x2400|pixel-7-pro"


def test_normalize_star_resolution_matches_x():
    """脏写法 4：`1080*2400` 与 `1080x2400`（还有全角 ×）必须等价。"""
    star = normalize_profile({"os": "android", "os_version": "13", "resolution": "1080*2400", "model": "Pixel 7 Pro"})
    letter_x = normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "Pixel 7 Pro"}
    )
    fullwidth = normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "1080×2400", "model": "Pixel 7 Pro"}
    )
    assert star == letter_x == fullwidth == "android-13|1080x2400|pixel-7-pro"


def test_normalize_orders_resolution_short_side_first():
    """脏写法 5：竖写分辨率 2400x1080 与 1080x2400 等价（短边在前）。"""
    assert normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "2400x1080", "model": "Pixel 7 Pro"}
    ) == normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "Pixel 7 Pro"}
    )


def test_normalize_strips_trailing_zero_version_segments():
    """脏写法 6：`Android 13.0.0` / `android-13.0` 与 `Android 13` 等价。"""
    a = normalize_profile({"os": "Android", "os_version": "13.0.0", "resolution": "1080x2400", "model": "Pixel 7 Pro"})
    b = normalize_profile({"os": "android", "os_version": "13.0", "resolution": "1080x2400", "model": "Pixel 7 Pro"})
    c = normalize_profile({"os": "Android", "os_version": 13, "resolution": "1080x2400", "model": "Pixel 7 Pro"})
    assert a == b == c == "android-13|1080x2400|pixel-7-pro"


def test_normalize_is_idempotent():
    once = normalize_profile("android14|1440x3120|pixel7pro")
    assert once == "android-14|1440x3120|pixel7pro"
    assert normalize_profile(once) == once


def test_normalize_keeps_minor_version():
    assert (
        normalize_profile({"os": "android", "os_version": "13.1", "resolution": "1080x2400", "model": "pixel-7-pro"})
        == "android-13.1|1080x2400|pixel-7-pro"
    )


# ---------------------------------------------------------------------------
# 2 组反例：不同档案必须不相等
# ---------------------------------------------------------------------------


def test_os_version_difference_is_not_equal():
    """反例 A：同一机型不同系统版本 ≠ 同一档案（跨大版本基线不可比）。"""
    assert not profiles_comparable(
        "android-13|1080x2400|pixel-7-pro", "android-14|1080x2400|pixel-7-pro"
    )
    assert normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "Pixel 7 Pro"}
    ) != normalize_profile(
        {"os": "android", "os_version": "14", "resolution": "1080x2400", "model": "Pixel 7 Pro"}
    )


def test_model_difference_is_not_equal():
    """反例 B：不同机型 ≠ 同一档案。"""
    assert not profiles_comparable(
        "android-13|1080x2400|pixel-7-pro", "android-13|1080x2400|pixel-8-pro"
    )
    assert normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "Pixel 7 Pro"}
    ) != normalize_profile(
        {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "Pixel 8 Pro"}
    )


def test_resolution_difference_is_not_equal():
    """反例补充：分辨率差异同样不可比（同机型不同缩放）。"""
    assert not profiles_comparable(
        "android-13|1080x2400|pixel-7-pro", "android-13|1440x3120|pixel-7-pro"
    )


# ---------------------------------------------------------------------------
# 缺失与非法输入：绝不静默相等
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "   ",
        {},
        {"os": "android", "os_version": "13"},
        {"os": "android", "resolution": "1080x2400"},
        {"os": "android", "os_version": "13", "resolution": "1080x2400"},
        "android-13|1080x2400",
        "not-a-profile",
        "android-13|not-a-resolution|pixel-7-pro",
        "sanfrancisco|1080x2400|pixel-7-pro",
        {"os": "android", "os_version": "13", "resolution": "wide", "model": "pixel"},
    ],
)
def test_invalid_profile_raises(bad):
    with pytest.raises(ProfileNormalizationError):
        normalize_profile(bad)


def test_missing_profile_is_not_comparable():
    """缺失不是「相等」：任一方为空都比较为 False。"""
    assert profiles_comparable(None, "android-13|1080x2400|pixel-7-pro") is False
    assert profiles_comparable("android-13|1080x2400|pixel-7-pro", None) is False
    assert profiles_comparable("", "") is False


def test_profile_components_roundtrip():
    assert profile_components("android13|1080x2400|Pixel 7 Pro") == (
        "android-13",
        "1080x2400",
        "pixel-7-pro",
    )


def test_normalize_accepts_nested_profile_key():
    assert (
        normalize_profile({"deviceProfile": "Android 14|1440x3120|Pixel 7 Pro"})
        == "android-14|1440x3120|pixel-7-pro"
    )
