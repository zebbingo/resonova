"""
从后端 Pydantic model 自动生成 TypeScript 类型定义。

用法:
    cd projects/resonova
    python scripts/gen_ts_types.py > frontend/src/api-types.gen.ts

原理:
    1. 导入 server.py 中的 Pydantic BaseModel 子类
    2. 使用 model_json_schema() 提取 JSON Schema
    3. 将 JSON Schema 转换为 TypeScript interface

依赖: pydantic >= 2.0 (Pydantic v2)
"""

import json
import re
import sys
from pathlib import Path

# 添加 backend 到 path
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))


def python_type_to_ts(annotation) -> str:
    """将 Python 类型注解转换为 TypeScript 类型字符串。"""
    if annotation is None or annotation is type(None):
        return "null"

    # 处理字符串形式的注解（如 "Optional[int]"）
    if isinstance(annotation, str):
        return _parse_type_string(annotation)

    # 基本类型映射
    _BASIC_MAP = {
        str: "string",
        int: "number",
        float: "number",
        bool: "boolean",
        dict: "Record<string, unknown>",
        list: "unknown[]",
    }
    if annotation in _BASIC_MAP:
        return _BASIC_MAP[annotation]

    # 处理 typing 模块的类型
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    if origin is list:
        if args:
            return f"{python_type_to_ts(args[0])}[]"
        return "unknown[]"

    if origin is dict:
        key_ts = python_type_to_ts(args[0]) if args else "string"
        val_ts = python_type_to_ts(args[1]) if args else "unknown"
        return f"Record<{key_ts}, {val_ts}>"

    # Optional[X] = Union[X, None]
    if origin is type(None) or (hasattr(annotation, "__class__") and annotation.__class__.__name__ == "NoneType"):
        return "null"

    # Union types (including Optional)
    if hasattr(annotation, "__union_params__") or (origin is not None and str(origin).startswith("typing.Union")):
        if args:
            non_none = [python_type_to_ts(a) for a in args if a is not type(None)]
            has_none = type(None) in args
            if has_none and non_none:
                inner = " | ".join(non_none)
                return f"({inner}) | null"
            elif non_none:
                return " | ".join(non_none)
            return "null"

    # Pydantic model → 引用其名称
    if hasattr(annotation, "model_fields"):
        return annotation.__name__

    return "unknown"


def _parse_type_string(s: str) -> str:
    """解析 Python 类型注解字符串为 TypeScript 类型。"""
    s = s.strip()

    if s in ("str", "string"):
        return "string"
    if s in ("int", "float"):
        return "number"
    if s in ("bool", "boolean"):
        return "boolean"
    if s in ("dict",):
        return "Record<string, unknown>"
    if s in ("list",):
        return "unknown[]"

    # Optional[X] → X | null
    m = re.match(r"Optional\[(.+)\]", s)
    if m:
        inner = _parse_type_string(m.group(1))
        return f"{inner} | null"

    # list[X] → X[]
    m = re.match(r"list\[(.+)\]", s, re.IGNORECASE)
    if m:
        inner = _parse_type_string(m.group(1))
        return f"{inner}[]"

    # dict[K, V] → Record<K, V>
    m = re.match(r"dict\[(.+?),\s*(.+?)\]", s, re.IGNORECASE)
    if m:
        k = _parse_type_string(m.group(1))
        v = _parse_type_string(m.group(2))
        return f"Record<{k}, {v}>"

    # int | str → number | string
    if " | " in s:
        parts = [_parse_type_string(p) for p in s.split(" | ")]
        return " | ".join(parts)

    return "unknown"


def extract_models_from_server():
    """从 server.py 中提取所有 Pydantic BaseModel 子类。"""
    try:
        import server
    except ImportError as e:
        print(f"Warning: Cannot import server.py: {e}", file=sys.stderr)
        return {}

    models = {}
    for name in dir(server):
        obj = getattr(server, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, __import__("pydantic").BaseModel)
            and obj is not __import__("pydantic").BaseModel
        ):
            models[name] = obj
    return models


def generate_ts_interface(name: str, model) -> str:
    """为一个 Pydantic model 生成 TypeScript interface。"""
    lines = [f"export interface {name} {{"]

    # 使用 model_json_schema 获取完整的类型信息
    try:
        schema = model.model_json_schema()
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        # 构建 $defs 的类型映射（用于解析 $ref）
        defs = schema.get("$defs", {})

        for field_name, field_info in properties.items():
            ts_type = _schema_type_to_ts(field_info, defs)
            optional = "?" if field_name not in required else ""
            lines.append(f"  {field_name}{optional}: {ts_type}")

    except AttributeError:
        # Pydantic v1 fallback
        for field_name, field_obj in model.__fields__.items():
            ts_type = python_type_to_ts(field_obj.outer_type_)
            optional = "?" if not field_obj.required else ""
            lines.append(f"  {field_name}{optional}: {ts_type}")

    lines.append("}")
    return "\n".join(lines)


def _schema_type_to_ts(info: dict, defs: dict) -> str:
    """将 JSON Schema 属性定义转换为 TypeScript 类型。"""
    if not isinstance(info, dict):
        return "unknown"

    # 处理 $ref
    if "$ref" in info:
        ref_name = info["$ref"].split("/")[-1]
        return ref_name

    # 处理 anyOf (Optional 类型)
    if "anyOf" in info:
        parts = []
        for item in info["anyOf"]:
            parts.append(_schema_type_to_ts(item, defs))
        return " | ".join(parts)

    # 处理 const
    if "const" in info:
        return json.dumps(info["const"])

    # 处理 enum
    if "enum" in info:
        return " | ".join(json.dumps(v) for v in info["enum"])

    # 基本类型
    json_type = info.get("type", "")
    if json_type == "string":
        return "string"
    if json_type == "integer" or json_type == "number":
        return "number"
    if json_type == "boolean":
        return "boolean"
    if json_type == "array":
        items = info.get("items", {})
        if items:
            return f"({_schema_type_to_ts(items, defs)})[]"
        return "unknown[]"
    if json_type == "object":
        # 尝试提取 additionalProperties
        add_props = info.get("additionalProperties", {})
        if add_props and isinstance(add_props, dict):
            val_type = _schema_type_to_ts(add_props, defs)
            return f"Record<string, {val_type}>"
        return "Record<string, unknown>"

    return "unknown"


# ── 前端已有类型列表（用于对比） ──
_FRONTEND_TYPES = {
    "TTSGenerateResponse",
    "TTSGenerateRequest",
    "TTSBatchRequest",
    "TTSBatchResponse",
    "TTSListResponse",
    "GeneratedVoice",
    "TTSPreset",
    "TTSOptionItem",
    "TTSRange",
    "TTSOptionsResponse",
    "TTSParams",
    "AudioItem",
    "FigurineConfig",
    "SttResult",
    "VadSegment",
    "VadSttResult",
    "AudioListResponse",
}


def main():
    models = extract_models_from_server()

    if not models:
        print("No Pydantic models found.", file=sys.stderr)
        return 1

    print("// ============================================================")
    print("// AUTO-GENERATED from backend Pydantic models")
    print("// DO NOT EDIT MANUALLY — run: python scripts/gen_ts_types.py")
    print("// ============================================================")
    print()

    # 只生成前端使用到的类型
    generated = set()
    for name in sorted(models.keys()):
        model = models[name]
        ts_code = generate_ts_interface(name, model)
        print(ts_code)
        print()
        generated.add(name)

    # 输出对比报告
    print("// ── Coverage Report ──")
    print(f"// Backend models: {len(models)}")
    print(f"// Generated: {len(generated)}")
    print(f"// Frontend types with backend equivalent: {len(_FRONTEND_TYPES & set(models.keys()))}")
    missing = _FRONTEND_TYPES - set(models.keys())
    if missing:
        print(f"// Frontend types WITHOUT backend model: {', '.join(sorted(missing))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
