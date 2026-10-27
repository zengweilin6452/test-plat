"""设备档案（device profile）规范化：基线可比性的唯一口径。

为什么需要规范化
----------------
vendor mobile_perf 的 `judge` 只用 `report["deviceProfile"]` 做**字符串相等**
比较（vendor/mobile_perf/src/mobile_perf/judge.py:100）。真机上同一个档案会被
写成 `Pixel 7 Pro / Android 13 / 1080x2400`、`android13|1080x2400|pixel7pro`、
`Android 13`、`android-13` 等十几种写法；直接字符串比较会把「同一台设备」
判成跨档案（假 not_tested），也会把「不同设备」误判成可比（假 passed）。
因此平台侧在**入库前**统一规范化，基线可比性用规范化字符串比较。

规范化目标格式
--------------
    <os>-<major>[-<minor>[-<patch>]]|<width>x<height>|<model-slug>
    android-13|1080x2400|pixel-7-pro

- 系统版本：`Android 13` / `android-13` / `Android 13.0.0` -> `android-13`（去尾零）；
  `Android 13.1` -> `android-13.1`。
- 分辨率：`1080*2400` / `1080X2400` / `1080 × 2400` -> `1080x2400`，短边在前。
- 机型：`Pixel 7 Pro` -> `pixel-7-pro`（小写、非法字符折叠为单个 `-`）。

不可规范化的输入一律抛 `ProfileNormalizationError`，**绝不返回空串或静默相等**：
库里的规范化档案永远是这张唯一的规范形，避免「脏写法入库后与别的脏写法相等」。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

__all__ = [
    "PROFILE_KEY_MODEL",
    "PROFILE_KEY_OS",
    "PROFILE_KEY_RESOLUTION",
    "ProfileNormalizationError",
    "canonical_profile_spec",
    "fingerprint_for",
    "normalize_profile",
    "profile_components",
    "profiles_comparable",
    "spec_from_probe",
    "unknown_profile_fingerprint",
    "unknown_profile_spec",
]


class ProfileNormalizationError(ValueError):
    """输入无法规范化为合法设备档案（缺失、无法解析或含不可比信息）。"""


# spec 字典里三种可能的键名（对齐原型 deviceProfile = "android14|1440x3120|pixel7pro"）
PROFILE_KEY_OS = ("os", "os_version", "osVersion", "system", "android_version", "platform")
PROFILE_KEY_RESOLUTION = (
    "resolution",
    "screen_resolution",
    "screenResolution",
    "screen",
    "display",
)
PROFILE_KEY_MODEL = ("model", "device_model", "deviceModel", "device", "product")

_OS_PATTERN = re.compile(
    r"^\s*(?P<os>android|ios|ipados|harmonyos|web)"
    r"\s*[-_/ ]?\s*(?P<version>[0-9]+(?:\.[0-9]+)*)?\s*$",
    re.IGNORECASE,
)

# 分辨率：1080x2400 / 1080*2400 / 1080 X 2400 / 1080 x 2400 / 1080,2400
_RESOLUTION_PATTERN = re.compile(
    r"^\s*(?P<w>[0-9]{2,5})\s*[xX*×,;:/]\s*(?P<h>[0-9]{2,5})\s*$"
)

_SLUG_NON_WORD = re.compile(r"[^0-9a-z]+")


def _pick(spec: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in spec and spec[key] not in (None, ""):
            return spec[key]
    # 大小写不同的写法（OS_Version / Screen_Resolution）
    lowered = {str(k).lower(): v for k, v in spec.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _resolve_os(spec: dict[str, Any]) -> Any:
    """系统版本常被拆成两个键写（`os`=`Android` + `os_version`=`13`）。

    只取第一个命中的键会丢掉版本号，把 `Android 13` 和 `Android 14`
    规范成同一个 `android`——这是最危险的假相等。因此这里按「名称键 + 版本键」
    组合：名称键只提供 OS 名，版本号必须来自版本键。

    同时也处理「版本写进了名称键」（`os`=`android-13`）以及
    `os_name` 与 `os_version` 并列的写法。
    """
    name_keys = ("os", "system", "platform", "os_name", "osName")
    version_keys = ("os_version", "osVersion", "android_version", "system_version")
    lowered = {str(k).lower(): v for k, v in spec.items()}

    def lookup(keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = spec.get(key, lowered.get(key.lower()))
            if value not in (None, ""):
                return value
        return None

    name = lookup(name_keys)
    version = lookup(version_keys)
    if name is None:
        return version
    if version is None:
        return name
    matched = _OS_PATTERN.match(_text(name))
    if matched is not None and matched.group("version"):
        # 名称本身已经含版本号（android-13 / Android 13），无需再拼接
        return name
    return f"{_text(name)} {_text(version)}"


def _text(value: Any) -> str:
    """值统一成字符串：全角转半角（NFKC），折叠空白。"""
    if isinstance(value, (int, float)):
        value = str(value)
    text = unicodedata.normalize("NFKC", str(value))
    return " ".join(text.split())


def _normalize_os(value: Any) -> str:
    text = _text(value)
    match = _OS_PATTERN.match(text)
    if match is None:
        raise ProfileNormalizationError(f"无法解析系统版本: {text!r}")
    os_name = match.group("os").lower()
    version = match.group("version")
    if not version:
        return os_name
    parts = version.split(".")
    # 去尾零：13.0.0 -> 13，13.1.0 -> 13.1
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    normalized_parts = [part.lstrip("0") or "0" for part in parts]
    return f"{os_name}-{'.'.join(normalized_parts)}"


def _normalize_resolution(value: Any) -> str:
    text = _text(value)
    match = _RESOLUTION_PATTERN.match(text)
    if match is None:
        raise ProfileNormalizationError(f"无法解析分辨率: {text!r}")
    width = int(match.group("w"))
    height = int(match.group("h"))
    if width <= 0 or height <= 0:
        raise ProfileNormalizationError(f"分辨率必须为正整数: {text!r}")
    short, long = sorted((width, height))
    return f"{short}x{long}"


def _normalize_model(value: Any) -> str:
    text = _text(value).lower()
    slug = _SLUG_NON_WORD.sub("-", text).strip("-")
    if not slug:
        raise ProfileNormalizationError(f"无法解析机型: {value!r}")
    return slug


def normalize_profile(spec: dict[str, Any] | str | None) -> str:
    """把一份设备档案 spec（dict 或字符串）规范化为平台唯一口径字符串。

    接受三种输入：
    1. dict：键名认 os/os_version/system、resolution/screen_resolution、
       model/device_model（兼容下划线、驼峰、Screen_Resolution 等写法）；
    2. 已经规范化的整串：`android-13|1080x2400|pixel-7-pro`（幂等）；
    3. vendor 的 deviceProfile 字符串：`android13|1440x3120|pixel7pro`、
       `Pixel 7 Pro / Android 13 / 1080x2400`（用 | 或 / 分段时逐个字段识别）。

    任何一段缺失或无法解析都抛 ProfileNormalizationError —— 缺失信息不能「当作相等」。
    """
    if spec is None:
        raise ProfileNormalizationError("设备档案为空，无法规范化")

    if isinstance(spec, str):
        return _normalize_profile_string(spec)

    if not isinstance(spec, dict):
        raise ProfileNormalizationError(
            f"设备档案必须是 dict 或 str，收到 {type(spec).__name__}"
        )

    os_value = _resolve_os(spec)
    resolution_value = _pick(spec, PROFILE_KEY_RESOLUTION)
    model_value = _pick(spec, PROFILE_KEY_MODEL)

    # 容错：三段被压进同一个值（例如 {"profile": "android13|1080x2400|pixel7pro"}）
    if os_value is None or resolution_value is None or model_value is None:
        for key in ("profile", "deviceProfile", "device_profile", "value"):
            candidate = spec.get(key)
            if isinstance(candidate, str):
                try:
                    return _normalize_profile_string(candidate)
                except ProfileNormalizationError:
                    continue

    missing = [
        name
        for name, value in (
            ("os", os_value),
            ("resolution", resolution_value),
            ("model", model_value),
        )
        if value in (None, "")
    ]
    if missing:
        raise ProfileNormalizationError(
            f"设备档案缺少字段 {missing}（现有键: {sorted(map(str, spec))}），不能规范化"
        )

    return "|".join(
        (
            _normalize_os(os_value),
            _normalize_resolution(resolution_value),
            _normalize_model(model_value),
        )
    )


def _normalize_profile_string(raw: str) -> str:
    text = _text(raw)
    if not text:
        raise ProfileNormalizationError("设备档案为空字符串，无法规范化")

    segments = [seg.strip() for seg in text.split("|") if seg.strip()]
    if len(segments) != 3:
        # 退路：用 / 或换行分段（"Pixel 7 Pro / Android 13 / 1080x2400"）
        alt = [seg.strip() for seg in re.split(r"\s*/\s*|\s*\n\s*", text) if seg.strip()]
        if len(alt) == 3:
            segments = alt
    if len(segments) != 3:
        raise ProfileNormalizationError(
            f"设备档案必须是「系统|分辨率|机型」三段，收到 {text!r}"
        )

    # 三段顺序不固定：按内容识别身份，识别不唯一就报错（不赌）
    roles: dict[str, str] = {}
    unmatched: list[str] = []
    for segment in segments:
        if "os" not in roles and _OS_PATTERN.match(segment):
            roles["os"] = segment
        elif "resolution" not in roles and _RESOLUTION_PATTERN.match(segment):
            roles["resolution"] = segment
        else:
            unmatched.append(segment)
    if len(unmatched) == 1 and "model" not in roles:
        roles["model"] = unmatched[0]
        unmatched = []
    if unmatched or len(roles) != 3:
        raise ProfileNormalizationError(
            f"设备档案三段身份无法唯一确定（os/resolution/model）: {text!r}"
        )
    return "|".join(
        (
            _normalize_os(roles["os"]),
            _normalize_resolution(roles["resolution"]),
            _normalize_model(roles["model"]),
        )
    )


def profile_components(profile: str) -> tuple[str, str, str]:
    """把规范化档案拆回 (os, resolution, model)；非法输入抛 ProfileNormalizationError。"""
    normalized = normalize_profile(profile)
    os_part, resolution_part, model_part = normalized.split("|")
    return os_part, resolution_part, model_part


def profiles_comparable(left: str | None, right: str | None) -> bool:
    """两份档案是否可比（规范化后全等才 True）。

    任一方缺失 -> False：缺失不是「相等」，跨档案必须判 not_tested。
    """
    if not left or not right:
        return False
    try:
        return normalize_profile(left) == normalize_profile(right)
    except ProfileNormalizationError:
        return False


# --------------------------------------------------------------------------- #
# 设备同步（device-registration.md D3）：adb 探测结果 -> 档案 spec 与指纹
# --------------------------------------------------------------------------- #
#: 规范化 os 段 -> spec 里的展示名（canonical spec 的唯一写法）
_OS_DISPLAY = {"android": "Android", "ios": "iOS", "ipados": "iPadOS", "harmonyos": "HarmonyOS", "web": "Web"}


def spec_from_probe(probe: dict[str, Any]) -> dict[str, str]:
    """adb 探测结果 -> 可入库的规范化档案 spec（四字段）。

    缺任何一段都在 normalize_profile 处抛 ProfileNormalizationError——
    半截档案不入库（缺失信息不能当作相等）。
    """
    spec = {
        "os_name": "Android",
        "os_version": str(probe.get("os_version") or ""),
        "screen_resolution": str(probe.get("screen_resolution") or ""),
        "model": str(probe.get("model") or ""),
    }
    normalize_profile(spec)  # 只做校验，返回值不带原始大小写
    return spec


def canonical_profile_spec(spec: dict[str, Any]) -> dict[str, str]:
    """从任意合法 spec 推导**规范化 spec**：同样的设备永远得到同一个 dict。

    model 取规范化后的 slug（小写）、分辨率短边在前、os 版本去尾零——
    `25102RKBEC` 与 `25102rkbec`、`2608x1200` 与 `1200x2608` 落到同一指纹。
    """
    normalized = normalize_profile(spec)
    os_part, resolution_part, model_part = normalized.split("|")
    os_name, _, os_version = os_part.partition("-")
    return {
        "os_name": _OS_DISPLAY.get(os_name, os_name),
        "os_version": os_version,
        "screen_resolution": resolution_part,
        "model": model_part,
    }


def fingerprint_for(spec: dict[str, Any]) -> str:
    """档案指纹：规范化 spec 的 SHA-256（对齐 0001 的列注释「规范化档案的 SHA-256」）。

    先经 canonical_profile_spec 归一，调用方传原始探测值还是规范化值结果一致。
    """
    payload = json.dumps(canonical_profile_spec(spec), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def unknown_profile_spec() -> dict[str, Any]:
    """未识别设备（unauthorized / 探测失败）的占位档案 spec（D3.3）。"""
    return {"unknown": True}


def unknown_profile_fingerprint(platform: str) -> str:
    """未识别档案的固定指纹：同 (platform) 恒等，靠唯一索引全局只建一行。"""
    payload = json.dumps(
        {"unknown": True, "platform": platform},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
