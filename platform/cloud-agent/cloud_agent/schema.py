"""A deliberately small JSON-Schema subset for tool arguments.

Only the keywords used by this service are implemented.  The goal is defensive
validation of model-produced arguments before any domain code runs, not a
general-purpose JSON-Schema implementation.
"""

import re


class SchemaError(ValueError):
    def __init__(self, path, message, keyword=None):
        self.path = path
        self.message = message
        self.keyword = keyword
        super(SchemaError, self).__init__("%s: %s" % (path, message))


def _typename(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches_type(value, expected):
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _format_path(path, key):
    if isinstance(key, int):
        return "%s[%d]" % (path, key)
    return "%s.%s" % (path, key)


def validate(instance, schema, path="$"):
    """Return a list of ``{"path", "message", "keyword"}`` errors.

    An empty list means the instance is valid.  The first failure in a branch
    is recorded; validation continues through sibling object properties and
    array items so the model gets useful feedback.
    """
    errors = []

    def add(location, message, keyword=None):
        errors.append({"path": location, "message": message, "keyword": keyword})

    def walk(value, rule, location):
        if not isinstance(rule, dict):
            add(location, "schema must be an object", "schema")
            return

        if "const" in rule and value != rule["const"]:
            add(location, "must equal %r" % (rule["const"],), "const")
            return

        if "enum" in rule:
            allowed = rule["enum"]
            if not isinstance(allowed, list):
                add(location, "schema enum must be an array", "enum")
                return
            if value not in allowed:
                add(
                    location,
                    "must be one of: %s" % ", ".join(repr(item) for item in allowed),
                    "enum",
                )
                return

        expected = rule.get("type")
        if expected is not None:
            candidates = expected if isinstance(expected, list) else [expected]
            if not any(_matches_type(value, item) for item in candidates):
                add(
                    location,
                    "expected %s, got %s" % ("/".join(str(item) for item in candidates), _typename(value)),
                    "type",
                )
                return

        if isinstance(value, dict):
            properties = rule.get("properties", {})
            if properties is None:
                properties = {}
            if not isinstance(properties, dict):
                add(location, "schema properties must be an object", "properties")
                return
            required = rule.get("required", [])
            if isinstance(required, list):
                for key in required:
                    if key not in value:
                        add(location, "missing required property %r" % (key,), "required")
            additional = rule.get("additionalProperties", True)
            for key, child in value.items():
                child_location = _format_path(location, key)
                if key in properties:
                    walk(child, properties[key], child_location)
                elif additional is False:
                    add(child_location, "property is not allowed", "additionalProperties")
                elif isinstance(additional, dict):
                    walk(child, additional, child_location)

        if isinstance(value, list):
            min_items = rule.get("minItems")
            max_items = rule.get("maxItems")
            if isinstance(min_items, int) and len(value) < min_items:
                add(location, "must contain at least %d item(s)" % min_items, "minItems")
            if isinstance(max_items, int) and len(value) > max_items:
                add(location, "must contain at most %d item(s)" % max_items, "maxItems")
            item_rule = rule.get("items")
            if isinstance(item_rule, dict):
                for index, item in enumerate(value):
                    walk(item, item_rule, _format_path(location, index))

        if isinstance(value, str):
            min_length = rule.get("minLength")
            max_length = rule.get("maxLength")
            if isinstance(min_length, int) and len(value) < min_length:
                add(location, "must be at least %d character(s)" % min_length, "minLength")
            if isinstance(max_length, int) and len(value) > max_length:
                add(location, "must be at most %d character(s)" % max_length, "maxLength")
            pattern = rule.get("pattern")
            if isinstance(pattern, str):
                try:
                    if re.search(pattern, value) is None:
                        add(location, "does not match required pattern", "pattern")
                except re.error:
                    add(location, "schema contains an invalid pattern", "pattern")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = rule.get("minimum")
            maximum = rule.get("maximum")
            if isinstance(minimum, (int, float)) and value < minimum:
                add(location, "must be >= %s" % minimum, "minimum")
            if isinstance(maximum, (int, float)) and value > maximum:
                add(location, "must be <= %s" % maximum, "maximum")

    walk(instance, schema, path)
    return errors


def error_summary(errors, limit=4):
    selected = errors[:limit]
    summary = "; ".join("%s %s" % (item["path"], item["message"]) for item in selected)
    if len(errors) > limit:
        summary += "; and %d more" % (len(errors) - limit)
    return summary
