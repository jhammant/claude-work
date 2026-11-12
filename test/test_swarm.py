"""Tests for bin/claude-swarm. No network, no Keychain, no real Claude: a fake
claude binary prints stream-json and records what it was given.

    python3 -m unittest discover -s test -p 'test_*.py'
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("claude_swarm", str(ROOT / "bin" / "claude-swarm"))
spec = importlib.util.spec_from_loader("claude_swarm", loader)
cs = importlib.util.module_from_spec(spec)
loader.exec_module(cs)

FAKE_CLAUDE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys, time
    args = sys.argv[1:]
    model = args[args.index("--model") + 1]
    if "claude-haiku-4-5" in args:
        print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed",
              "unifiedWindows": {"seven_day": {"utilization": 0.33, "resetsAt": 2000000000}}}}))
        sys.exit(0)
    prompt = sys.stdin.read()
    mode = os.environ.get("FAKE_MODE", "ok")
    began = time.time()
    if mode == "silent":
        time.sleep(30)
        sys.exit(0)
    print(json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}), flush=True)
    print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed",
          "unifiedWindows": {"seven_day": {"utilization": 0.42, "resetsAt": 2000000000}}}}), flush=True)
    print(json.dumps({"type": "assistant", "message": {}}), flush=True)
    if mode == "slow":
        time.sleep(1.0)
    with open(os.environ["FAKE_RECORD"], "a") as f:
        f.write(json.dumps({"argv": args, "account": os.environ.get("CLAUDE_SWARM_ACCOUNT"),
                            "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "prompt": prompt,
                            "cwd": os.getcwd(), "model": model, "began": began, "ended": time.time()}) + "\\n")
    if mode == "fable-limit" and "fable" in model:
        print(json.dumps({"type": "result", "is_error": True, "result": "Fable usage limit reached",
                          "session_id": "sess-1"}))
        sys.exit(1)
    print(json.dumps({"type": "result", "is_error": False, "result": "done on " + model,
                      "session_id": "sess-1", "total_cost_usd": 0.01, "num_turns": 2}))
""")


class SwarmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-r", "-f", str(self.tmp)])
        self.saved = {name: getattr(cs, name) for name in
                      ("CONFIG", "STATE", "QUOTAMAX_CACHE", "read_token", "has_token")}
        self.addCleanup(lambda: [setattr(cs, k, v) for k, v in self.saved.items()])
        cs.CONFIG = self.tmp / "accounts.json"
        cs.STATE = self.tmp / "state"
        cs.QUOTAMAX_CACHE = self.tmp / "no-quotamax.json"
        self.tokens = {"claude-work-oauth": "tok-work", "claude-swarm-two": "tok-two"}
        cs.read_token = lambda item: self.tokens.get(item)
        cs.has_token = lambda item: item in self.tokens
        fake = self.tmp / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)
        self.record = self.tmp / "record.jsonl"
        self.env = {"CLAUDE_BIN": str(fake), "FAKE_RECORD": str(self.record), "WATCH_INTERVAL": "0.1",
                    "CLAUDE_SWARM_WAIT_INTERVAL": "0.1", "FAKE_MODE": "ok"}
        self.old_env = {k: os.environ.get(k) for k in list(self.env) + ["START_TIMEOUT"]}
        os.environ.update(self.env)
        self.addCleanup(self.restore_env)
        self.work = self.tmp / "repo"
        self.work.mkdir()
        self.prompt = self.tmp / "brief.md"
        self.prompt.write_text("Write hello.py\n")

    def restore_env(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def two_accounts(self, **extra):
        cfg = {"accounts": [{"name": "work", "keychain": "claude-work-oauth"},
                            {"name": "two", "keychain": "claude-swarm-two", **extra}]}
        cs.CONFIG.write_text(json.dumps(cfg))
        return cs.load_config()

    def quota(self, name, pct):
        cs.save_quota(name, {"status": "allowed", "unifiedWindows": {"seven_day": {"utilization": pct / 100}}})

    def records(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def quiet(self, fn, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = fn(*args, **kwargs)
        return code, out.getvalue()

    # -- models --------------------------------------------------------------

    def test_alias_resolves_and_full_id_passes_through(self):
        # Arrange
        cfg = cs.load_config()
        # Act
        fable = cs.resolve_model(cfg, None)
        full = cs.resolve_model(cfg, "claude-opus-5-5")
        new = cs.resolve_model(cfg, "claude-fable-9-9")
        # Assert
        self.assertEqual(fable, ("fable", "claude-fable-5-2"))
        self.assertEqual(full, ("opus", "claude-opus-5-5"))
        self.assertEqual(new, ("claude-fable-9-9", "claude-fable-9-9"))

    def test_unknown_model_is_refused(self):
        cfg = cs.load_config()
        with self.assertRaises(cs.SwarmError):
            cs.resolve_model(cfg, "gpt-6")

    def test_model_command_repoints_an_alias_and_keeps_the_others(self):
        # Arrange
        cfg = cs.load_config()
        # Act
        self.quiet(cs.main, ["model", "fable", "claude-fable-5-3"])
        cfg = cs.load_config()
        # Assert
        self.assertEqual(cfg["models"]["fable"], "claude-fable-5-3")
        self.assertEqual(cfg["models"]["opus"], "claude-opus-5-5")
        self.assertEqual(oct(cs.CONFIG.stat().st_mode & 0o777), "0o600")

    # -- picking an account ----------------------------------------------------

    def test_pick_prefers_more_headroom(self):
        # Arrange
        cfg = self.two_accounts()
        self.quota("work", 60)
        self.quota("two", 20)
        # Act
        ready, reasons, _ = cs.candidates(cfg, "fable")
        # Assert
        self.assertEqual([a["name"] for a in ready], ["two", "work"])
        self.assertEqual(reasons, [])

    def test_pick_skips_an_account_at_its_cap_or_without_a_token(self):
        # Arrange
        cfg = self.two_accounts(max_pct=50)
        self.quota("two", 55)
        del self.tokens["claude-work-oauth"]
        # Act
        ready, reasons, busy_only = cs.candidates(cfg, "fable")
        # Assert
        self.assertEqual(ready, [])
        self.assertFalse(busy_only)
        self.assertIn("work: no token", reasons[0])
        self.assertIn("two: weekly 55% is at its 50% cap", reasons[1])

    def test_pick_skips_an_account_not_set_up_for_the_model(self):
        cfg = self.two_accounts(models=["opus"])
        ready, reasons, _ = cs.candidates(cfg, "fable")
        self.assertEqual([a["name"] for a in ready], ["work"])
        self.assertIn("two: not set up for fable", reasons)

    def test_a_full_account_counts_as_busy_not_blocked(self):
        # Arrange
        cfg = cs.load_config()
        cfg["accounts"][0]["max_agents"] = 1
        cs.register("other-task", cfg["accounts"][0], "fable", str(self.work))
        # Act
        ready, reasons, busy_only = cs.candidates(cfg, "fable")
        # Assert
        self.assertEqual(ready, [])
        self.assertTrue(busy_only)
        self.assertEqual(reasons, ["work: all 1 agents busy"])

    # -- running ----------------------------------------------------------------

    def test_run_passes_the_brief_on_stdin_and_the_token_only_in_the_environment(self):
        # Arrange
        cfg = cs.load_config()
        # Act
        code, out = self.quiet(cs.run_task, cfg, slug="hello", directory=str(self.work), prompt=self.prompt,
                               effort="high")
        # Assert
        self.assertEqual(code, 0)
        rec = self.records()[0]
        self.assertEqual(rec["prompt"], "Write hello.py\n")
        self.assertEqual(rec["token"], "tok-work")
        self.assertNotIn("tok-work", " ".join(rec["argv"]))
        self.assertEqual(rec["model"], "claude-fable-5-2")
        self.assertEqual(rec["argv"][rec["argv"].index("--effort") + 1], "high")
        self.assertEqual(Path(rec["cwd"]).resolve(), self.work.resolve())
        self.assertIn("exited 0", out)

    def test_run_writes_the_final_message_meta_and_quota_and_frees_its_slot(self):
        cfg = cs.load_config()
        self.quiet(cs.run_task, cfg, slug="hello", directory=str(self.work), prompt=self.prompt)
        runs = cs.STATE / "runs"
        self.assertEqual((runs / "hello.txt").read_text(), "done on claude-fable-5-2")
        meta = json.loads((runs / "hello.meta.json").read_text())
        self.assertEqual((meta["account"], meta["session"], meta["code"]), ("work", "sess-1", 0))
        self.assertEqual(cs.read_quota(cfg["accounts"][0])["week"], 42)
        self.assertEqual(cs.live_jobs(), [])

    def test_run_stops_a_task_that_never_starts(self):
        # Arrange
        cfg = cs.load_config()
        os.environ["FAKE_MODE"] = "silent"
        os.environ["START_TIMEOUT"] = "1"
        # Act
        code, out = self.quiet(cs.run_task, cfg, slug="stuck", directory=str(self.work), prompt=self.prompt)
        # Assert
        self.assertEqual(code, 3)
        self.assertIn("no turn started", out)
        self.assertEqual(cs.live_jobs(), [])

    def test_a_fable_limit_continues_the_same_session_on_opus(self):
        # Arrange
        cfg = cs.load_config()
        os.environ["FAKE_MODE"] = "fable-limit"
        # Act
        code, out = self.quiet(cs.run_task, cfg, slug="big", directory=str(self.work), prompt=self.prompt)
        # Assert
        self.assertEqual(code, 0)
        first, second = self.records()
        self.assertEqual(first["model"], "claude-fable-5-2")
        self.assertEqual(second["model"], "claude-opus-5-5")
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], "sess-1")
        self.assertIn("fable", cs.cooling("work"))
        self.assertIn("continuing on opus", out)
        # The cooled model is skipped until its reset.
        self.assertEqual(cs.candidates(cfg, "fable")[0], [])

    def test_resume_goes_back_to_the_same_account_and_session(self):
        # Arrange
        cfg = self.two_accounts()
        self.quota("work", 90)
        self.quiet(cs.run_task, cfg, slug="t1", directory=str(self.work), prompt=self.prompt)
        fix = self.tmp / "fix.md"
        fix.write_text("Tests fail; fix them.\n")
        # Act
        code, _ = self.quiet(cs.main, ["resume", "t1", "--prompt", str(fix)])
        # Assert
        self.assertEqual(code, 0)
        first, second = self.records()
        self.assertEqual(first["account"], "two")
        self.assertEqual(second["account"], "two")
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], "sess-1")
        self.assertTrue((cs.STATE / "runs" / "t1.fix1.meta.json").exists())

    def test_fan_runs_every_brief_and_never_more_than_the_agent_count(self):
        # Arrange
        self.two_accounts()
        os.environ["FAKE_MODE"] = "slow"
        briefs = []
        for name in ("a", "b", "c"):
            path = self.tmp / f"{name}.md"
            path.write_text(f"task {name}\n")
            briefs.append(str(path))
        # Act
        code, out = self.quiet(cs.main, ["fan", "--dir", str(self.work), "--agents", "2"] + briefs)
        # Assert
        self.assertEqual(code, 0, out)
        recs = self.records()
        self.assertEqual(sorted(r["prompt"] for r in recs), ["task a\n", "task b\n", "task c\n"])
        overlap = max(sum(1 for o in recs if o["began"] < r["ended"] and r["began"] < o["ended"]) for r in recs)
        self.assertLessEqual(overlap, 2)
        self.assertIn("fan: 3 of 3 done", out)

    def test_worktree_gives_the_task_its_own_branch(self):
        # Arrange
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)
        subprocess.run(["git", "-C", str(self.work), "-c", "user.email=t@example.com", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        cfg = cs.load_config()
        # Act
        code, _ = self.quiet(cs.run_task, cfg, slug="wt", directory=str(self.work), prompt=self.prompt,
                             worktree=True)
        # Assert
        self.assertEqual(code, 0)
        cwd = Path(self.records()[0]["cwd"]).resolve()
        self.assertEqual(cwd.name, "repo--cs-wt")
        branch = subprocess.run(["git", "-C", str(cwd), "branch", "--show-current"], capture_output=True, text=True)
        self.assertEqual(branch.stdout.strip(), "cs/wt")

    def test_add_registers_an_account_and_prints_its_sign_in(self):
        code, out = self.quiet(cs.main, ["add", "client-x", "--max-agents", "2", "--models", "fable,opus"])
        cfg = cs.load_config()
        self.assertEqual(code, 0)
        self.assertEqual(cfg["accounts"][1]["keychain"], "claude-swarm-client-x")
        self.assertEqual(cfg["accounts"][1]["max_agents"], 2)
        self.assertIn("CLAUDE_WORK_KEYCHAIN=claude-swarm-client-x claude-work login", out)

    def test_probe_records_a_reading(self):
        cfg = cs.load_config()
        info = cs.probe(cfg["accounts"][0])
        self.assertEqual(info["status"], "allowed")
        self.assertEqual(cs.read_quota(cfg["accounts"][0])["week"], 33)


if __name__ == "__main__":
    unittest.main()
