import json
import unittest

from backend.library import ApplyError, plan_apply

SPEC = "import { test, expect } from '@playwright/test';\ntest('%s', async () => { expect(1).toBe(1); });\n"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
COLLECTION = json.dumps({"info": {"name": "API", "schema": SCHEMA}, "item": [{"name": "r", "request": {"method": "GET", "url": "http://x"}}]})


def spec(title="a"):
    return SPEC % title


def saved(*names, revision=1):
    return {n: {"revision": revision, "text": spec(n)} for n in names}


def plan(existing=None, col=None, **body):
    return plan_apply(existing or {}, col, body)


def error(existing=None, col=None, **body):
    try:
        plan_apply(existing or {}, col, body)
    except ApplyError as exc:
        return exc
    raise AssertionError("expected ApplyError")


class SaveTests(unittest.TestCase):
    def test_new_file_is_saved(self):
        p = plan(specs=[{"name": "a.spec.ts", "text": spec(), "revision": None}])
        self.assertEqual([u["name"] for u in p["upsert"]], ["a.spec.ts"])
        self.assertFalse(p["upsert"][0]["exists"])
        self.assertEqual(p["summary"]["saved_specs"], 1)

    def test_update_with_matching_revision(self):
        p = plan(saved("a.spec.ts", revision=3), specs=[{"name": "a.spec.ts", "text": spec("new"), "revision": 3}])
        self.assertTrue(p["upsert"][0]["exists"])

    def test_unchanged_file_is_not_rewritten(self):
        p = plan(saved("a.spec.ts"), specs=[{"name": "a.spec.ts", "text": spec("a.spec.ts"), "revision": 1}])
        self.assertEqual(p["upsert"], [])
        self.assertEqual(p["summary"]["saved_specs"], 0)

    def test_empty_request_is_fine(self):
        p = plan()
        self.assertEqual(p["summary"], {"saved_specs": 0, "removed_specs": 0, "saved_collection": False, "removed_collection": False})

    def test_invalid_files_are_listed_by_name(self):
        e = error(specs=[{"name": "a.spec.js", "text": spec()}, {"name": "b.spec.ts", "text": "nonsense"}])
        self.assertEqual(e.status, 422)
        self.assertEqual(set(e.detail["files"]), {"a.spec.js", "b.spec.ts"})

    def test_one_bad_file_blocks_everything(self):
        e = error(specs=[{"name": "good.spec.ts", "text": spec()}, {"name": "bad.spec.ts", "text": "x"}])
        self.assertEqual(e.status, 422)

    def test_duplicate_names_in_one_request(self):
        e = error(specs=[{"name": "a.spec.ts", "text": spec()}, {"name": "a.spec.ts", "text": spec("b")}])
        self.assertIn("a.spec.ts", e.detail["files"])

    def test_names_that_differ_only_by_case(self):
        e = error(specs=[{"name": "A.spec.ts", "text": spec()}, {"name": "a.spec.ts", "text": spec("b")}])
        self.assertEqual(e.status, 422)
        e = error(saved("A.spec.ts"), specs=[{"name": "a.spec.ts", "text": spec("b"), "revision": None}])
        self.assertIn("letter case", e.detail["files"]["a.spec.ts"][0])

    def test_case_only_rename_is_allowed_when_the_old_name_is_deleted(self):
        p = plan(saved("A.spec.ts"), specs=[{"name": "a.spec.ts", "text": spec("b"), "revision": None}],
                 delete_specs=[{"name": "A.spec.ts", "revision": 1}])
        self.assertEqual(p["delete"], ["A.spec.ts"])
        self.assertEqual([u["name"] for u in p["upsert"]], ["a.spec.ts"])

    def test_save_and_delete_the_same_file_is_refused(self):
        e = error(saved("a.spec.ts"), specs=[{"name": "a.spec.ts", "text": spec("z"), "revision": 1}],
                  delete_specs=[{"name": "a.spec.ts", "revision": 1}])
        self.assertEqual(e.status, 422)

    def test_library_size_limit(self):
        many = [{"name": f"s{i}.spec.ts", "text": spec(str(i)), "revision": None} for i in range(51)]
        e = error(specs=many)
        self.assertEqual(e.status, 422)
        self.assertIn("at most 50", e.detail)

    def test_limit_counts_deletes(self):
        existing = saved(*[f"s{i}.spec.ts" for i in range(50)])
        p = plan(existing, specs=[{"name": "new.spec.ts", "text": spec("n"), "revision": None}],
                 delete_specs=[{"name": "s0.spec.ts", "revision": 1}])
        self.assertEqual(len(p["upsert"]), 1)


class DeleteTests(unittest.TestCase):
    def test_delete_existing(self):
        p = plan(saved("a.spec.ts", "b.spec.ts"), delete_specs=[{"name": "a.spec.ts", "revision": 1}])
        self.assertEqual(p["delete"], ["a.spec.ts"])

    def test_delete_missing_is_a_quiet_success(self):
        p = plan(saved("a.spec.ts"), delete_specs=[{"name": "ghost.spec.ts", "revision": 4}])
        self.assertEqual(p["delete"], [])

    def test_delete_without_revision_is_unconditional(self):
        p = plan(saved("a.spec.ts", revision=9), delete_specs=[{"name": "a.spec.ts"}])
        self.assertEqual(p["delete"], ["a.spec.ts"])

    def test_delete_listed_twice(self):
        e = error(saved("a.spec.ts"), delete_specs=[{"name": "a.spec.ts"}, {"name": "a.spec.ts"}])
        self.assertEqual(e.status, 422)


class ConflictTests(unittest.TestCase):
    def reasons(self, e):
        return [(c["kind"], c["name"], c["reason"]) for c in e.detail["conflicts"]]

    def test_update_of_a_file_changed_elsewhere(self):
        e = error(saved("a.spec.ts", revision=5), specs=[{"name": "a.spec.ts", "text": spec("z"), "revision": 4}])
        self.assertEqual(e.status, 409)
        self.assertEqual(self.reasons(e), [("spec", "a.spec.ts", "changed")])

    def test_update_of_a_file_deleted_elsewhere(self):
        e = error(specs=[{"name": "a.spec.ts", "text": spec("z"), "revision": 2}])
        self.assertEqual(self.reasons(e), [("spec", "a.spec.ts", "deleted")])

    def test_new_file_when_the_name_was_taken_elsewhere(self):
        e = error(saved("a.spec.ts"), specs=[{"name": "a.spec.ts", "text": spec("z"), "revision": None}])
        self.assertEqual(self.reasons(e), [("spec", "a.spec.ts", "exists")])

    def test_delete_of_a_file_changed_elsewhere(self):
        e = error(saved("a.spec.ts", revision=2), delete_specs=[{"name": "a.spec.ts", "revision": 1}])
        self.assertEqual(self.reasons(e), [("spec", "a.spec.ts", "changed")])

    def test_one_conflict_blocks_every_change(self):
        e = error(saved("a.spec.ts", revision=2),
                  specs=[{"name": "new.spec.ts", "text": spec("n"), "revision": None}],
                  delete_specs=[{"name": "a.spec.ts", "revision": 1}])
        self.assertEqual(e.status, 409)

    def test_validation_is_reported_before_conflicts(self):
        e = error(saved("a.spec.ts", revision=2), specs=[{"name": "a.spec.ts", "text": "bad", "revision": 1}])
        self.assertEqual(e.status, 422)


class CollectionPlanTests(unittest.TestCase):
    def col(self, revision=1, name="c.json", text=COLLECTION):
        return {"revision": revision, "name": name, "text": text}

    def test_new_collection(self):
        p = plan(collection={"name": "c.json", "text": COLLECTION, "revision": None})
        self.assertEqual(p["collection"]["requests"], 1)
        self.assertFalse(p["collection"]["exists"])

    def test_replace_collection_with_a_different_name(self):
        p = plan(col=self.col(2), collection={"name": "other.json", "text": COLLECTION, "revision": 2})
        self.assertTrue(p["collection"]["exists"])

    def test_unchanged_collection_is_skipped(self):
        p = plan(col=self.col(), collection={"name": "c.json", "text": COLLECTION, "revision": 1})
        self.assertIsNone(p["collection"])

    def test_stale_collection_revision(self):
        e = error(col=self.col(3), collection={"name": "c.json", "text": COLLECTION + " ", "revision": 2})
        self.assertEqual(e.status, 409)

    def test_collection_deleted_elsewhere(self):
        e = error(collection={"name": "c.json", "text": COLLECTION, "revision": 1})
        self.assertEqual(e.detail["conflicts"][0]["reason"], "deleted")

    def test_collection_created_elsewhere(self):
        e = error(col=self.col(), collection={"name": "c.json", "text": COLLECTION + " ", "revision": None})
        self.assertEqual(e.detail["conflicts"][0]["reason"], "exists")

    def test_delete_collection(self):
        p = plan(col=self.col(), delete_collection={"revision": 1})
        self.assertTrue(p["delete_collection"])

    def test_delete_missing_collection_is_a_quiet_success(self):
        p = plan(delete_collection={"revision": 7})
        self.assertFalse(p["delete_collection"])

    def test_delete_collection_with_stale_revision(self):
        e = error(col=self.col(4), delete_collection={"revision": 3})
        self.assertEqual(e.status, 409)

    def test_save_and_delete_collection_together(self):
        e = error(col=self.col(), collection={"name": "c.json", "text": COLLECTION, "revision": 1}, delete_collection={"revision": 1})
        self.assertEqual(e.status, 422)

    def test_invalid_collection(self):
        e = error(collection={"name": "c.json", "text": "{oops", "revision": None})
        self.assertIn("c.json", e.detail["files"])

    def test_environment_file_is_refused(self):
        e = error(collection={"name": "env.json", "text": json.dumps({"id": "1", "values": []}), "revision": None})
        self.assertIn("environment", e.detail["files"]["env.json"][0])


if __name__ == "__main__":
    unittest.main()