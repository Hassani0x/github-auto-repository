import copy
import unittest
from pathlib import Path
import yaml
from src.security import SafetyError, validate, verify


class Controls(unittest.TestCase):
    def test_defaults_and_invalid_options(self):
        cfg = yaml.safe_load(Path("config.yaml").read_text())
        validate(cfg)
        for group, key, value in (("automation","max_daily_runs",16),
                                  ("security","protect_existing_repositories",False),
                                  ("repository","prefix","../"), ("repository","private",False),
                                  ("automation","enabled","false")):
            with self.subTest(key=key):
                changed = copy.deepcopy(cfg)
                changed[group][key] = value
                with self.assertRaises(SafetyError):
                    validate(changed)

    def test_identity_checks(self):
        uid = "a"*32
        name = "auto-calculator-20260101000000-" + uid
        user = dict(id=1, login="owner")
        repo = dict(id=12, owner=user, created_at="yesterday", name=name, full_name="owner/"+name,
                    private=True, description="Lifecycle test "+uid)
        receipt = dict(id=12, owner_id=1, owner="owner", name=name, created_at="yesterday")
        run = dict(id=uid,name=name,receipt=receipt)
        def check(candidate, controller="owner/main", controller_id="123"):
            verify(candidate, run, user, "auto-calculator-", controller, controller_id)
        check(repo)
        for key,value in (("id",13),("owner",dict(id=2,login="other")),("private",False),
                          ("created_at","today"),("name","other"),("description","changed")):
            with self.subTest(key=key), self.assertRaises(SafetyError):
                check(dict(repo, **{key:value}))
        with self.assertRaises(SafetyError):
            check(repo, controller_id="12")
        with self.assertRaises(SafetyError):
            check(repo, controller="owner/"+name)

