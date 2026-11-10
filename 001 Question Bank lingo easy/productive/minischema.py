"""Tiny JSON-Schema subset validator (no third-party dependency).

Supports: type (incl. lists), required, properties, additionalProperties (bool or schema), items, enum, const, pattern, minimum, maximum,
minItems, minLength, oneOf, $ref ('#/$defs/...'). Unknown keywords are ignored (and listed in IGNORED so tests can assert coverage).
"""
import re

IGNORED = {"$schema", "$id", "title", "description", "default", "examples", "format", "$comment"}
TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict, "null": type(None)}


def _type_ok(v, t):
    ts = t if isinstance(t, list) else [t]
    for x in ts:
        if x == "integer" and isinstance(v, bool):
            continue
        if x == "number" and isinstance(v, bool):
            continue
        if isinstance(v, TYPES[x]):
            return True
    return False


def validate(instance, schema, root=None, path="$"):
    root = root or schema
    errs = []
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate(instance, node, root, path)
    if "oneOf" in schema:
        ok = [validate(instance, s, root, path) for s in schema["oneOf"]]
        if sum(1 for e in ok if not e) != 1:
            errs.append(f"{path}: must match exactly one of oneOf")
    if "type" in schema and not _type_ok(instance, schema["type"]):
        return errs + [f"{path}: expected {schema['type']}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in enum")
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append(f"{path}: does not match pattern {schema['pattern']}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, x in enumerate(instance):
                errs += validate(x, schema["items"], root, f"{path}[{i}]")
    if isinstance(instance, dict):
        for k in schema.get("required", []):
            if k not in instance:
                errs.append(f"{path}: missing required '{k}'")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs += validate(v, props[k], root, f"{path}.{k}")
            else:
                ap = schema.get("additionalProperties", True)
                if ap is False:
                    errs.append(f"{path}: unexpected property '{k}'")
                elif isinstance(ap, dict):
                    errs += validate(v, ap, root, f"{path}.{k}")
    return errs
