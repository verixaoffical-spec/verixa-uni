import json
import unittest

from backend.validators import analyse_collection, analyse_spec, invalid_name_reason, validate_collection, validate_spec

GOOD_SPEC = r"""import { test, expect } from '@playwright/test';
// test('commented out', async () => {});
test.describe('checkout', () => {
  test('pays with card', async ({ page }) => {
    await page.goto('https://shop.test/');
    await expect(page).toHaveURL(/https?:\/\//);
  });
  test.skip('guest checkout', async () => { await expect(1).toBe(1); });
});
"""

SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def collection(**overrides):
    data = {
        "info": {"name": "API", "schema": SCHEMA},
        "item": [
            {"name": "Auth", "item": [{
                "name": "Login",
                "request": {"method": "POST", "url": {"raw": "{{baseUrl}}/login"}},
                "event": [{"listen": "test", "script": {"exec": ['pm.test("ok", () => {})']}}],
            }]},
            {"name": "Ping", "request": "https://x.io/ping"},
        ],
    }
    data.update(overrides)
    return json.dumps(data)


class SpecTests(unittest.TestCase):
    def test_good_spec(self):
        result = analyse_spec(GOOD_SPEC)
        self.assertEqual(result["errors"], [])
        self.assertEqual([(t["title"], t["line"], t["mode"]) for t in result["tests"]],
                         [("pays with card", 4, ""), ("guest checkout", 8, "skip")])

    def test_missing_import(self):
        self.assertIn("Missing import from '@playwright/test'", analyse_spec("test('a', () => { expect(1) })")["errors"])

    def test_truncated_file(self):
        text = "import {test} from '@playwright/test';\ntest('a', () => { expect(1)"
        self.assertTrue(any("incomplete" in e for e in analyse_spec(text)["errors"]))

    def test_child_process_blocked(self):
        text = "import {test} from '@playwright/test';import cp from 'child_process';test('a',()=>{expect(1)})"
        self.assertTrue(any("child_process" in e for e in analyse_spec(text)["errors"]))

    def test_no_tests(self):
        self.assertTrue(any("No tests" in e for e in analyse_spec("import {test} from '@playwright/test';")["errors"]))

    def test_only_and_no_assertion_warn(self):
        text = "import {test} from '@playwright/test';\ntest.only('a', async () => {});"
        warnings = analyse_spec(text)["warnings"]
        self.assertEqual(len(warnings), 2)

    def test_file_level_rules(self):
        self.assertIn("Only .spec.ts files are accepted", validate_spec("a.spec.js", GOOD_SPEC)["errors"])
        self.assertIn("File is empty", validate_spec("a.spec.ts", "")["errors"])
        self.assertTrue(any("cannot contain" in e for e in validate_spec("../a.spec.ts", GOOD_SPEC)["errors"]))
        self.assertIn("File name needs a name before .spec.ts", validate_spec(".spec.ts", GOOD_SPEC)["errors"])
        self.assertIn("File contains invalid characters", validate_spec("a.spec.ts", "x\ud800")["errors"])
        self.assertIn("File is not plain text", validate_spec("a.spec.ts", GOOD_SPEC + "\x00")["errors"])
        self.assertTrue(any("limit" in e for e in validate_spec("a.spec.ts", "x" * 600_000)["errors"]))
        self.assertEqual(validate_spec("a.spec.ts", GOOD_SPEC)["errors"], [])


class NameTests(unittest.TestCase):
    def test_bad_names(self):
        for name in ["", " a.spec.ts", "a.spec.ts ", "a/b.spec.ts", "a\\b.spec.ts", "a:b.spec.ts", "a?.spec.ts", "a\x00.spec.ts",
                     "a.", "CON.spec.ts", "nul.json", "com1.spec.ts", "x" * 201]:
            self.assertIsNotNone(invalid_name_reason(name), repr(name))

    def test_good_names(self):
        for name in ["login.spec.ts", "Checkout flow (v2).spec.ts", "shop.postman_collection.json", "\u00e9t\u00e9.spec.ts", "a.b.spec.ts"]:
            self.assertIsNone(invalid_name_reason(name), repr(name))


class CollectionTests(unittest.TestCase):
    def test_good_collection(self):
        result = analyse_collection(collection())
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["requests"]), 2)
        self.assertEqual(result["folders"], 1)
        self.assertEqual(len(result["warnings"]), 1)

    def test_environment_file(self):
        result = analyse_collection(json.dumps({"id": "1", "name": "env", "values": []}))
        self.assertIn("environment", result["errors"][0])

    def test_old_schema(self):
        text = collection(info={"name": "x", "schema": "https://schema.getpostman.com/json/collection/v1.0.0/collection.json"})
        self.assertTrue(any("schema" in e for e in analyse_collection(text)["errors"]))

    def test_bad_json(self):
        errors = analyse_collection("{oops")["errors"]
        self.assertTrue(any(e.startswith("Not valid JSON") for e in errors))
        self.assertIn("Add a real file", errors[0])  # the plain message comes first

    def test_not_real_names(self):
        from backend.validators import analyse_spec, not_real_text
        for fake in ("1234", "!!!!", "---", "aaaa", "xxxxx"):
            self.assertTrue(not_real_text(fake), fake)
        for real in ("a", "Login", "user can log in", "GET 200", "x2"):
            self.assertFalse(not_real_text(real), real)
        text = ("import { test, expect } from '@playwright/test';\n"
                "test('12345', async () => { expect(1).toBe(1); });\n")
        self.assertTrue(any("are not real" in e for e in analyse_spec(text)["errors"]))
        bad = collection(item=[{"name": "1234", "request": {"method": "GET", "url": "https://x.test"}}])
        self.assertTrue(any("not a real request name" in e for e in analyse_collection(bad)["errors"]))

    def test_bad_request(self):
        text = collection(item=[{"name": "a", "request": {"method": "FETCH", "url": ""}}])
        errors = analyse_collection(text)["errors"]
        self.assertIn('"a" uses unsupported method FETCH', errors)
        self.assertIn('"a" has no URL', errors)

    def test_file_level_rules(self):
        self.assertIn("Only .json collection exports are accepted", validate_collection("c.txt", collection())["errors"])
        self.assertEqual(validate_collection("c.postman_collection.json", collection())["errors"], [])
        self.assertTrue(validate_collection("a/b.json", collection())["errors"])

    def test_odd_shapes_do_not_crash(self):
        for odd in ['[]', 'null', '"x"', '{"info":null,"item":[null,1,"a",[]]}',
                    json.dumps({"info": {"name": "x", "schema": SCHEMA}, "item": [{"name": "r", "request": 5}]}),
                    "[" * 100000]:
            self.assertIn("errors", analyse_collection(odd))


if __name__ == "__main__":
    unittest.main()