import unittest

from cloud_agent.schema import error_summary, validate


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = {
            "type": "object",
            "properties": {
                "route_id": {"type": "string", "minLength": 1, "maxLength": 8},
                "checks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "string", "enum": ["a", "b"]},
                },
                "count": {"type": "integer", "minimum": 1},
                "enabled": {"type": "boolean"},
            },
            "required": ["route_id", "checks"],
            "additionalProperties": False,
        }

    def test_valid(self):
        instance = {"route_id": "r1", "checks": ["a", "b"], "count": 2, "enabled": True}
        self.assertEqual(validate(instance, self.schema), [])

    def test_missing_required(self):
        errors = validate({"route_id": "r1"}, self.schema)
        self.assertTrue(any(item["keyword"] == "required" for item in errors))

    def test_additional_property_rejected(self):
        errors = validate({"route_id": "r1", "checks": ["a"], "extra": 1}, self.schema)
        self.assertTrue(any(item["path"] == "$.extra" for item in errors))
        self.assertTrue(any(item["keyword"] == "additionalProperties" for item in errors))

    def test_wrong_type(self):
        errors = validate({"route_id": 3, "checks": ["a"]}, self.schema)
        self.assertTrue(any(item["path"] == "$.route_id" and item["keyword"] == "type" for item in errors))

    def test_boolean_is_not_integer(self):
        errors = validate({"route_id": "r1", "checks": ["a"], "count": True}, self.schema)
        self.assertTrue(any(item["path"] == "$.count" and item["keyword"] == "type" for item in errors))

    def test_enum_and_item_path(self):
        errors = validate({"route_id": "r1", "checks": ["a", "z"]}, self.schema)
        self.assertTrue(any(item["path"] == "$.checks[1]" and item["keyword"] == "enum" for item in errors))

    def test_min_items(self):
        errors = validate({"route_id": "r1", "checks": []}, self.schema)
        self.assertTrue(any(item["keyword"] == "minItems" for item in errors))

    def test_max_length(self):
        errors = validate({"route_id": "too-long-id", "checks": ["a"]}, self.schema)
        self.assertTrue(any(item["keyword"] == "maxLength" for item in errors))

    def test_error_summary_is_bounded(self):
        errors = [{"path": "$.x", "message": "bad"} for _ in range(6)]
        summary = error_summary(errors, limit=2)
        self.assertIn("and 4 more", summary)


if __name__ == "__main__":
    unittest.main()
