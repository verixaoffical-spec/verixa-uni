import unittest

from backend.accounts import (
    Throttle, email_problem, hash_password, name_problem, normalize_email, normalize_name, password_problem,
    safe_next, verify_password,
)

APP = "/verixa_prototype.html"


class EmailTests(unittest.TestCase):
    def test_normalizes_case_space_and_width(self):
        self.assertEqual(normalize_email("  Ada@Example.COM \n"), "ada@example.com")
        self.assertEqual(normalize_email("ａｄａ@example.com"), "ada@example.com")  # full-width letters

    def test_accepts_ordinary_addresses(self):
        for email in ("a@b.co", "first.last+tag@sub.company.io", "x_y-z@domain.travel"):
            self.assertIsNone(email_problem(email), email)

    def test_refuses_broken_addresses(self):
        for email in ("", "plain", "@x.com", "a@", "a@b", "a@b.c", "a b@c.com", "a@@b.com", "a..b@c.com",
                      "a@b..com", "a" * 65 + "@b.com", "a@" + "b" * 250 + ".com"):
            self.assertIsNotNone(email_problem(normalize_email(email)), email)

    def test_refuses_garbage(self):
        garbage = [
            # symbols only, or a symbol at the start or end of the part before @
            "'''@x.com", "---@x.com", "+++@x.com", "%%%@x.com", "_@x.com", ".a@x.com", "a.@x.com", "-a@x.com", "a-@x.com",
            # broken domains
            "a@.com", "a@com.", "a@-x.com", "a@x-.com", "a@x_y.com", "a@x.c0m", "a@x.123", "a@1.2.3.4", "a@[1.2.3.4]",
            "a@localhost", "a@x.com.", "a@x." + "t" * 25, "a@" + "b" * 64 + ".com",
            # characters that never belong in an email
            "<script>@x.com", "a@x.com<script>", "a@x.com\x00", "a\x00@x.com", "a\tb@x.com", "a;b@x.com", "a,b@x.com",
            "a(b)@x.com", 'a"b@x.com', "a<b@x.com", "a@x.com/path", "a@x.com?q=1", "javascript:alert(1)@x.com",
            "' or 1=1--", "admin'--@x.com", "a@x.com; drop table users", "😀@x.com", "a@😀.com", "a@b@c.com",
            # length limits: 64 before @, 253 after it, 254 in total
            "a" * 65 + "@x.com", "a@" + ("b" * 60 + ".") * 5 + "com",
        ]
        for email in garbage:
            self.assertIsNotNone(email_problem(normalize_email(email)), repr(email))

    def test_accepts_real_addresses_at_the_edges(self):
        longest_local = "a" * 64 + "@x.com"
        long_domain = "a@" + ".".join(["b" * 63] * 3) + ".com"  # a 63 character part is the most allowed
        for email in ("o'brien@x.com", "first.last+tag@x.co.uk", "1@2.com", "a1@b.io", "a@b.c.d.e.f.com",
                      "user@xn--bcher-kva.ch", "a@x." + "t" * 24, longest_local, long_domain, "a_b%c+d@x.com"):
            self.assertIsNone(email_problem(normalize_email(email)), email)


class NameTests(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(normalize_name("  Ada \t  Lovelace "), "Ada Lovelace")

    def test_rules(self):
        self.assertIsNone(name_problem("Zoë O'Brien-Smith"))
        self.assertIsNone(name_problem("李小龙"))
        self.assertIsNotNone(name_problem(""))
        self.assertIsNotNone(name_problem("x" * 51))
        self.assertIsNotNone(name_problem("<script>"))
        self.assertIsNotNone(name_problem("bell\x07"))
        self.assertIsNotNone(name_problem("zero​width"))

    def test_length_from_2_to_50(self):
        self.assertEqual(name_problem("A"), "Use at least 2 characters")
        self.assertIsNone(name_problem("Al"))
        self.assertIsNone(name_problem("A" * 50))
        self.assertEqual(name_problem("A" * 51), "Use 50 characters or fewer")

    def test_refuses_garbage(self):
        for name in ("123", "Ada 2", "@@@", "-Ada", "'Ada", ".", "Ada<b>", "Ada; drop table users", "😀", "Ada 😀",
                     "<img src=x onerror=alert(1)>", "${7*7}", "{{7*7}}", "Ada_Lovelace", "Ada@home"):
            self.assertIsNotNone(name_problem(normalize_name(name)), repr(name))


class PasswordTests(unittest.TestCase):
    def test_rules(self):
        self.assertIsNone(password_problem("correct horse 9", "ada@example.com", "Ada Lovelace"))
        cases = {
            "": "Enter", "short1": "at least 8", "a1" * 65: "128", "        ": "only spaces",
            "abcdefgh": "letter and one number", "12345678": "letter and one number",
            "Password123": "too common", "lovelace99x": None, "adalovelace1": "name", "myada_1234": None,
        }
        for pw, expected in cases.items():
            got = password_problem(pw, "ada@example.com", "Ada Lovelace")
            if expected is None:
                self.assertIsNone(got, pw)
            else:
                self.assertIn(expected, got or "", pw)

    def test_email_inside_password(self):
        self.assertIn("email", password_problem("xxadamsmith9", "adamsmith@x.io", ""))

    def test_spaces_are_kept(self):
        stored = hash_password(" secret 123 ")
        self.assertTrue(verify_password(" secret 123 ", stored))
        self.assertFalse(verify_password("secret 123", stored))


class HashTests(unittest.TestCase):
    def test_round_trip_and_salt(self):
        a, b = hash_password("hunter2hunter2"), hash_password("hunter2hunter2")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("scrypt$"))
        self.assertTrue(verify_password("hunter2hunter2", a))
        self.assertFalse(verify_password("hunter2hunter3", a))

    def test_unicode(self):
        self.assertTrue(verify_password("pässwörd 1 🔒", hash_password("pässwörd 1 🔒")))

    def test_missing_or_corrupt_hash(self):
        for stored in (None, "", "bcrypt$x", "scrypt$1$2", "scrypt$abc$8$1$AAAA$AAAA", "scrypt$16384$8$1$!!$!!"):
            self.assertFalse(verify_password("anything1", stored), stored)


class NextTests(unittest.TestCase):
    def test_allows_local_paths(self):
        self.assertEqual(safe_next("/verixa_prototype.html", APP), "/verixa_prototype.html")
        self.assertEqual(safe_next("/verixa_prototype.html?x=1#library", APP), "/verixa_prototype.html?x=1#library")

    def test_refuses_anything_off_site(self):
        for target in (None, "", "https://evil.com", "//evil.com", "/\\evil.com", "\\\\evil.com", "evil.com",
                       "javascript:alert(1)", "/\x00x", "/login", "/signup?next=/x", "/" + "a" * 600):
            self.assertEqual(safe_next(target, APP), APP, repr(target))


class ThrottleTests(unittest.TestCase):
    def test_blocks_after_limit_and_recovers(self):
        t = Throttle(limit=3, window=60)
        for i in range(3):
            self.assertEqual(t.retry_after("k", at=100 + i), 0)
            t.fail("k", at=100 + i)
        self.assertEqual(t.retry_after("k", at=103), 57)
        self.assertEqual(t.retry_after("other", at=103), 0)
        self.assertEqual(t.retry_after("k", at=160.5), 0)  # the first failure has left the window

    def test_clear(self):
        t = Throttle(limit=1, window=60)
        t.fail("k", at=1)
        self.assertGreater(t.retry_after("k", at=2), 0)
        t.clear("k")
        self.assertEqual(t.retry_after("k", at=2), 0)


if __name__ == "__main__":
    unittest.main()
