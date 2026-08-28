import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "backend" / "superproductivity.py"
SPEC = importlib.util.spec_from_file_location("superproductivity", MODULE_PATH)
assert SPEC is not None
sp = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(sp)


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return next(self.replies)


class BackendTests(unittest.TestCase):
    def test_mutation_result_preserves_message_and_validates_optional_metadata(self):
        legacy = sp.mutation_result("start", "task", "succeeded", "done", True, message="Task started")
        self.assertEqual(legacy["message"], "Task started")
        self.assertNotIn("messageKey", legacy)
        self.assertNotIn("messageArgs", legacy)

        semantic = sp.fixed_mutation_result(
            "start", "task", "succeeded", "done", True, message="Task started",
        )
        self.assertEqual(semantic["messageKey"], "task-started")

        localized = sp.mutation_result(
            "add", "task", "succeeded", "done", True,
            message="Task added", messageKey="custom-result", messageArgs={"title": "--unsafe"},
        )
        self.assertEqual(localized["message"], "Task added")
        self.assertEqual(localized["messageKey"], "custom-result")
        self.assertEqual(localized["messageArgs"], {"title": "--unsafe"})

        for values in (
            {"messageKey": ""}, {"messageKey": 1}, {"messageKey": "bad\nkey"},
            {"messageArgs": []}, {"messageArgs": "bad"},
        ):
            with self.subTest(values=values), self.assertRaises(sp.BridgeError):
                sp.mutation_result("start", "task", "failed", "preflight", False, **values)

    def test_fixed_mutation_messages_all_have_unique_semantic_keys(self):
        self.assertEqual(len(sp._MESSAGE_KEYS), len(set(sp._MESSAGE_KEYS.values())))
        for message, key in sp._MESSAGE_KEYS.items():
            with self.subTest(message=message):
                result = sp.fixed_mutation_result(
                    "start", "task", "failed", "preflight", False, message=message,
                )
                self.assertEqual((result["message"], result["messageKey"]), (message, key))

        with self.assertRaisesRegex(sp.BridgeError, "Missing semantic key"):
            sp.fixed_mutation_result(
                "start", "task", "failed", "preflight", False, message="Unregistered fixed text",
            )

    def test_dynamic_upstream_diagnostic_stays_raw_even_if_text_matches_fixed_message(self):
        result = sp.mutation_result(
            "start", "task", "failed", "dispatch", False, message="Task started",
        )
        self.assertEqual(result["message"], "Task started")
        self.assertNotIn("messageKey", result)

    def test_parse_native_like_subset(self):
        parsed = sp.parse_shorthand(
            "Write report 1.5h +Wor @tomorrow",
            [{"id": "p1", "title": "Work"}],
            [],
            dt.date(2026, 8, 24),
        )
        self.assertEqual(parsed["title"], "Write report")
        self.assertEqual(parsed["timeEstimate"], 5_400_000)
        self.assertEqual(parsed["projectId"], "p1")
        self.assertEqual(parsed["dueDay"], "2026-08-25")

    def test_parse_spent_and_estimate_and_next_weekday(self):
        parsed = sp.parse_shorthand("Review 15m/1h @mon", [], [], dt.date(2026, 8, 24))
        self.assertEqual(parsed["timeSpent"], 900_000)
        self.assertEqual(parsed["timeEstimate"], 3_600_000)
        self.assertEqual(parsed["dueDay"], "2026-08-31")

    def test_parse_summed_prefixed_and_spent_only_durations(self):
        self.assertEqual(sp.parse_shorthand("Plan t1h 30m", [], [])["timeEstimate"], 5_400_000)
        self.assertEqual(sp.parse_shorthand("Plan 1h/2h", [], [])["timeSpent"], 3_600_000)
        spent_only = sp.parse_shorthand("Plan 30m/", [], [])
        self.assertEqual(spent_only["title"], "Plan")
        self.assertEqual(spent_only["timeSpent"], 1_800_000)
        self.assertNotIn("timeEstimate", spent_only)

    def test_exact_normalized_project_title_wins_over_prefix_matches(self):
        projects = [
            {"id": "long", "title": "Important Project Archive"},
            {"id": "short", "title": "  IMPORTANT   project "},
        ]
        parsed = sp.parse_shorthand("Ship +Important Project", projects, [])
        self.assertEqual(parsed, {"title": "Ship", "projectId": "short"})

    def test_exact_whole_project_match_beats_shorter_project(self):
        projects = [
            {"id": "long", "title": "Important Project Archive"},
            {"id": "short", "title": "Important Project"},
        ]
        parsed = sp.parse_shorthand("Ship +Important Project Archive", projects, [])
        self.assertEqual(parsed, {"title": "Ship", "projectId": "long"})

    def test_project_prefix_must_identify_exactly_one_project(self):
        projects = [
            {"id": "work", "title": "Work"},
            {"id": "workout", "title": "Workout"},
        ]
        with self.assertRaisesRegex(sp.BridgeError, r"Ambiguous project: \+wor"):
            sp.parse_shorthand("Ship +Wor", projects, [])

    def test_unique_project_prefix_is_accepted(self):
        projects = [
            {"id": "work", "title": "Work"},
            {"id": "workout", "title": "Workout"},
        ]
        parsed = sp.parse_shorthand("Ship +Worko", projects, [])
        self.assertEqual(parsed, {"title": "Ship", "projectId": "workout"})

    def test_exact_project_title_wins_over_longer_prefix_match(self):
        projects = [
            {"id": "work", "title": "Work"},
            {"id": "workout", "title": "Workout"},
        ]
        parsed = sp.parse_shorthand("Ship +Work", projects, [])
        self.assertEqual(parsed, {"title": "Ship", "projectId": "work"})

    def test_unknown_or_ambiguous_project_errors(self):
        with self.assertRaisesRegex(sp.BridgeError, "Unknown project"):
            sp.parse_shorthand("Ship +Missing", [], [])
        with self.assertRaisesRegex(sp.BridgeError, "Ambiguous project"):
            sp.parse_shorthand("Ship +Wor", [{"id": "1", "title": "Work"}, {"id": "2", "title": "work"}], [])

    def test_tags_match_exactly_case_insensitively_and_dedupe_ids(self):
        tags = [
            {"id": "focus", "title": "Focus"},
            {"id": "urgent", "title": "urgent"},
            {"id": "other", "title": "focus later"},
        ]
        parsed = sp.parse_shorthand("Ship #FOCUS #Urgent #focus", [], tags)
        self.assertEqual(parsed, {
            "title": "Ship",
            "projectId": "INBOX_PROJECT",
            "tagIds": ["focus", "urgent"],
        })

    def test_metadata_removal_uses_matched_span(self):
        parsed = sp.parse_shorthand("ref#focus #focus", [], [{"id": "focus", "title": "Focus"}])
        self.assertEqual(parsed, {
            "title": "ref#focus",
            "projectId": "INBOX_PROJECT",
            "tagIds": ["focus"],
        })

    def test_unknown_tag_fails_clearly(self):
        with self.assertRaisesRegex(sp.BridgeError, r"Unknown tag: #missing"):
            sp.parse_shorthand("Ship #missing", [], [{"id": "t", "title": "focus"}])

    def test_defaults_to_inbox(self):
        self.assertEqual(sp.parse_shorthand("Ship", [], []), {"title": "Ship", "projectId": "INBOX_PROJECT"})

    def test_add_fetches_metadata_then_creates_task(self):
        client = FakeClient([
            [{"id": "p", "title": "Work"}],
            [{"id": "focus", "title": "Focus"}, {"id": "urgent", "title": "Urgent"}],
            {"id": "new"},
        ])
        reply = sp.add(client, "Ship 30m +Work #FOCUS #Urgent #focus")
        self.assertEqual(reply["state"], "succeeded")
        self.assertEqual(reply["task"], {"id": "new"})
        self.assertEqual(client.calls, [
            ("GET", "/projects", None),
            ("GET", "/tags", None),
            ("POST", "/tasks", {
                "title": "Ship",
                "projectId": "p",
                "tagIds": ["focus", "urgent"],
                "timeEstimate": 1_800_000,
            }),
        ])

    def test_status_shapes_current_task(self):
        task = {"id": "1", "title": "Work", "timeEstimate": 1000, "timeSpent": 250, "projectId": "p", "extra": True}
        client = FakeClient([[], [{"id": "p", "title": "Project"}], [], task])
        with mock.patch.object(sp.time, "time_ns", side_effect=[1_111_000_000, 1_234_000_000]):
            result = sp.status(client)
            self.assertEqual(result["task"]["projectTitle"], "Project")
            self.assertEqual(result["signedRemainingMs"], 750)
            self.assertEqual(result["fetchedAt"], 1234)
            self.assertEqual(result["todayFetchedAt"], 1111)
        self.assertEqual(client.calls, [
            ("GET", "/tasks?tagId=TODAY", None),
            ("GET", "/projects", None),
            ("GET", "/tasks?includeDone=true", None),
            ("GET", "/task-control/current", None),
        ])

    def test_status_normalizes_null_task(self):
        with mock.patch.object(sp.time, "time_ns", side_effect=[1_000_000, 2_000_000]):
            result = sp.status(FakeClient([[], [], [], None]))
            self.assertIsNone(result["task"])
            self.assertEqual(result["fetchedAt"], 2)

    def test_status_schedules_only_fresh_incomplete_top_level_today_entries(self):
        def task(task_id, due, **values):
            return {
                "id": task_id, "title": task_id, "timeEstimate": 10, "timeSpent": 0,
                "dueWithTime": due, **values,
            }

        today = [
            task("later", 300), task("tie-first", 200), task("done", 100, isDone=True),
            task("child", 150, parentId="parent"), task("tie-second", 200),
            task("zero", 0), task("infinite", float("inf")),
        ]
        result = sp.status(FakeClient([today, [], [], None]))
        self.assertEqual([value["id"] for value in result["scheduledTasks"]], ["tie-first", "tie-second", "later"])

    def test_status_failed_today_has_no_schedule_sample(self):
        client = mock.Mock()
        client.request.side_effect = [sp.DispatchUnknown("today down"), [], [], None]
        result = sp.status(client)
        self.assertIsNone(result["scheduledTasks"])
        self.assertIsNone(result["todayFetchedAt"])
        self.assertFalse(result["context"]["todayOk"])

    def test_status_filters_malformed_done_and_orders_chronologically(self):
        def task(task_id, **values):
            return {
                "id": task_id, "title": task_id, "timeEstimate": 10, "timeSpent": 1,
                **values,
            }

        today = [
            task("first", dueDay="2026-08-24"),
            task("done", isDone=True),
            task("child", parentId="parent"),
            task("bad-negative", timeSpent=-1),
            task("bad-infinite", timeEstimate=float("inf")),
            task("second", dueWithTime=1234),
            "not a task",
        ]
        result = sp.status(FakeClient([today, [], [], None]))
        self.assertEqual([item["id"] for item in result["todayTasks"]], ["second", "first", "child"])
        self.assertEqual(result["todayTasks"][1]["dueDay"], "2026-08-24")
        self.assertEqual(result["todayTasks"][0]["dueWithTime"], 1234)

    def test_status_rejects_malformed_current_and_response_list(self):
        malformed = {"id": "current", "title": "Bad", "timeEstimate": "10", "timeSpent": 0}
        with self.assertRaisesRegex(sp.BridgeError, "malformed task"):
            sp.status(FakeClient([[], [], [], malformed]))
        result = sp.status(FakeClient([{}, [], [], None]))
        self.assertFalse(result["context"]["todayOk"])

    def test_status_stops_after_either_request_failure(self):
        client = FakeClient([])
        client.request = mock.Mock(side_effect=sp.BridgeError("failed"))
        with self.assertRaisesRegex(sp.BridgeError, "failed"):
            sp.status(client)
        self.assertEqual(client.request.call_count, 4)

    def test_status_hydrates_only_named_incomplete_children_in_parent_order(self):
        def task(task_id, **values):
            return {
                "id": task_id, "title": values.pop("title", task_id),
                "timeEstimate": 10, "timeSpent": 0, **values,
            }

        today = [task("parent", title="Parent", projectId="p", subTaskIds=["second", "first", "missing", "done", "second"])]
        bulk = [
            task("unrelated"),
            task("first", parentId="parent", projectId="p", subTaskIds=["nested"]),
            task("nested", parentId="first"),
            task("second", parentId="parent", projectId="p"),
            task("second", title="duplicate", parentId="parent"),
            task("done", parentId="parent", isDone=True),
        ]
        result = sp.status(FakeClient([today, [{"id": "p", "title": "Project"}], bulk, None]))
        self.assertEqual([item["id"] for item in result["todayTasks"]], ["parent", "second", "first"])
        self.assertEqual(result["todayTasks"][1]["title"], "second")
        for child in result["todayTasks"][1:]:
            self.assertEqual((child["parentTitle"], child["projectTitle"], child["depth"]), ("Parent", "Project", 1))
        self.assertNotIn("unrelated", {item["id"] for item in result["todayTasks"]})
        self.assertNotIn("nested", {item["id"] for item in result["todayTasks"]})
        self.assertIn("missing-child", result["context"]["warnings"])
        self.assertTrue(result["context"]["tasksOk"])

    def test_status_done_retained_child_is_hidden_without_missing_warning(self):
        parent = {"id": "parent", "title": "Parent", "timeEstimate": 10, "timeSpent": 0,
                  "subTaskIds": ["done"]}
        done = {"id": "done", "title": "Done", "timeEstimate": 10, "timeSpent": 10,
                "parentId": "parent", "isDone": True}
        client = FakeClient([[parent], [], [done], None])

        result = sp.status(client)

        self.assertEqual([value["id"] for value in result["todayTasks"]], ["parent"])
        self.assertNotIn("missing-child", result["context"]["warnings"])
        self.assertIn(("GET", "/tasks?includeDone=true", None), client.calls)

    def test_status_keeps_today_and_current_when_bulk_tasks_fail(self):
        parent = {"id": "parent", "title": "Parent", "timeEstimate": 10, "timeSpent": 0, "subTaskIds": ["child"]}
        current = {"id": "current", "title": "Current", "timeEstimate": 10, "timeSpent": 1}
        client = mock.Mock()
        def request(_method, path, _body=None):
            if path == "/tasks?tagId=TODAY":
                return [parent]
            if path == "/projects":
                return []
            if path == "/tasks?includeDone=true":
                raise sp.DispatchUnknown("bulk down")
            return current
        client.request.side_effect = request
        result = sp.status(client)
        self.assertEqual([item["id"] for item in result["todayTasks"]], ["parent"])
        self.assertEqual(result["task"]["id"], "current")
        self.assertEqual(result["context"], {
            "todayOk": True,
            "projectsOk": True,
            "tasksOk": False,
            "warnings": ["tasks-unavailable", "missing-child"],
        })
        self.assertEqual(client.request.call_args_list[-1], mock.call("GET", "/task-control/current"))

    def test_start_posts_json_body_then_requires_exact_readback(self):
        current = {"id": "opaque / ID", "title": "Opaque", "timeEstimate": 0, "timeSpent": 0}
        client = FakeClient([{"id": "opaque / ID", "subTaskIds": []}, {}, current])
        result = sp.start(client, "opaque / ID")
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(client.calls, [
            ("GET", "/tasks/opaque%20%2F%20ID", None),
            ("POST", "/task-control/current", {"taskId": "opaque / ID"}),
            ("GET", "/task-control/current", None),
        ])

    def test_start_rejects_invalid_ids_before_network_access(self):
        for value in ("", "x" * 256, "line\nbreak", "nul\0byte", "control\u0085", "bidi\u202e"):
            with self.subTest(value=repr(value)):
                client = FakeClient([])
                result = sp.start(client, value)
                self.assertEqual((result["state"], result["stage"]), ("failed", "validation"))
                self.assertEqual(client.calls, [])

    def test_start_rejects_mismatched_readback_without_retry(self):
        current = {"id": "other", "title": "Other", "timeEstimate": 1, "timeSpent": 0}
        client = FakeClient([{"id": "wanted", "subTaskIds": []}, {}, current])
        self.assertEqual(sp.start(client, "wanted")["state"], "unknown")
        self.assertEqual(len(client.calls), 3)

    @mock.patch.object(sp.shutil, "which")
    @mock.patch.object(sp.subprocess, "run")
    def test_alert_uses_safe_notification_argv_and_default_player(self, run, which):
        run.return_value.returncode = 0
        which.side_effect = lambda name: "/bin/pw-play" if name == "pw-play" else None
        result, code = sp.alert("  Finish\nreport  ")
        self.assertEqual(code, 0)
        self.assertTrue(result["notification"]["ok"])
        self.assertTrue(result["sound"]["ok"])
        self.assertEqual(run.call_args_list[0].args[0], [
            "notify-send", "--urgency=critical", "--icon=alarm-symbolic", "--", "Super Productivity", "Finish report",
        ])
        self.assertEqual(run.call_args_list[1].args[0], ["pw-play", "--volume", "1.00", str(sp.DEFAULT_SOUND)])
        self.assertEqual(run.call_args_list[0].kwargs["timeout"], sp.NOTIFICATION_TIMEOUT)
        self.assertEqual(run.call_args_list[1].kwargs["timeout"], sp.SOUND_PLAYBACK_TIMEOUT)
        self.assertEqual(run.call_count, 2)

    @mock.patch.object(sp.subprocess, "run")
    def test_notification_defaults_and_localized_text_use_safe_argv(self, run):
        run.return_value.returncode = 0
        sp.test_notification("normal")
        self.assertEqual(run.call_args.args[0], [
            "notify-send", "--urgency=normal", "--icon=alarm-symbolic", "--",
            "Super Productivity", "Notification test",
        ])

        run.reset_mock()
        sp.test_notification("normal", "  --Übersicht\n", "  --Alles\tbereit  ")
        self.assertEqual(run.call_args.args[0], [
            "notify-send", "--urgency=normal", "--icon=alarm-symbolic", "--",
            "--Übersicht", "--Alles bereit",
        ])

    @mock.patch.object(sp.subprocess, "run")
    def test_notification_omitted_defaults_remain_byte_for_byte(self, run):
        run.return_value.returncode = 0
        sp.test_notification("normal")
        self.assertEqual(run.call_args.args[0][-2:], ["Super Productivity", "Notification test"])

        run.reset_mock()
        sp.alert("Task", silent=True)
        self.assertEqual(run.call_args.args[0][-2:], ["Super Productivity", "Task"])

    @mock.patch.object(sp.subprocess, "run")
    def test_explicit_empty_or_control_only_notification_fields_are_rejected(self, run):
        for invoke in (
            lambda value: sp.test_notification("normal", value, "Body"),
            lambda value: sp.test_notification("normal", "Title", value),
            lambda value: sp.alert("Body", silent=True, notification_title=value),
            lambda value: sp.alert(value, silent=True),
        ):
            for value in ("", "   ", "\n\t", "\u200b\u202e"):
                with self.subTest(invoke=invoke, value=repr(value)), self.assertRaisesRegex(
                    sp.BridgeError, "must not be empty",
                ):
                    invoke(value)
        run.assert_not_called()

    @mock.patch.object(sp.subprocess, "run")
    def test_alert_accepts_a_sanitized_notification_title(self, run):
        run.return_value.returncode = 0
        sp.alert("  --Aufgabe\n", silent=True, notification_title="  --Produktivität\t")
        self.assertEqual(run.call_args.args[0], [
            "notify-send", "--urgency=critical", "--icon=alarm-symbolic", "--",
            "--Produktivität", "--Aufgabe",
        ])

    @mock.patch.object(sp.shutil, "which")
    @mock.patch.object(sp.subprocess, "run")
    def test_alert_uses_first_available_player_and_never_falls_through_failure(self, run, which):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=7)]
        which.side_effect = lambda name: f"/bin/{name}" if name in ("paplay", "canberra-gtk-play") else None
        result, code = sp.alert("Done")
        self.assertEqual(code, 0)
        self.assertFalse(result["sound"]["ok"])
        self.assertEqual(run.call_args_list[1].args[0][0], "paplay")
        self.assertEqual(run.call_count, 2)

    @mock.patch.object(sp.subprocess, "run")
    def test_silent_alert_only_notifies_once(self, run):
        run.return_value.returncode = 0
        result, code = sp.alert("Done", "critical", "/not/read", silent=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["sound"], {"requested": False, "volume": 100, "ok": False})
        self.assertEqual(run.call_count, 1)

    @mock.patch.object(sp.shutil, "which")
    def test_player_volume_argv_and_fallback_selection(self, which):
        path = Path("/tmp/tone.wav")
        for volume, pw_value, pa_value in ((0, "0.00", "0"), (50, "0.50", "32768"), (100, "1.00", "65536")):
            with self.subTest(player="pw-play", volume=volume):
                which.side_effect = lambda name: "/bin/pw-play" if name == "pw-play" else None
                self.assertEqual(sp._player_command(path, volume), ["pw-play", "--volume", pw_value, str(path)])
            with self.subTest(player="paplay", volume=volume):
                which.side_effect = lambda name: "/bin/paplay" if name == "paplay" else None
                self.assertEqual(sp._player_command(path, volume), ["paplay", "--volume", pa_value, str(path)])

        which.side_effect = lambda name: "/bin/canberra-gtk-play" if name == "canberra-gtk-play" else None
        for volume, db_value in ((0, "-200.00"), (50, "-6.02"), (100, "0.00")):
            with self.subTest(player="canberra-gtk-play", volume=volume):
                self.assertEqual(
                    sp._player_command(path, volume),
                    ["canberra-gtk-play", f"--volume={db_value}", "-f", str(path)],
                )

    def test_readme_documents_volume_range_and_default_for_sound_commands(self):
        readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
        self.assertIn("preview-sound [--sound <path>] [--volume <0-100>]", readme)
        self.assertIn(
            "alert --urgency <low|normal|critical> [--sound <path>|--silent] [--volume <0-100>] -- <title>",
            readme,
        )
        self.assertIn("`--volume` accepts 0 through 100 and defaults to 100 for `preview-sound` and `alert`.", readme)

    @mock.patch.object(sp.shutil, "which", return_value=None)
    @mock.patch.object(sp.subprocess, "run")
    def test_alert_reports_independent_partial_failures_without_sensitive_values(self, run, _which):
        run.return_value.returncode = 1
        secret = "private title"
        result, code = sp.alert(secret, "critical", "/outside/private.wav")
        self.assertEqual(code, 1)
        self.assertFalse(result["notification"]["ok"])
        self.assertFalse(result["sound"]["ok"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("/outside/private.wav", json.dumps(result))
        self.assertEqual(run.call_count, 1)

    def test_custom_sound_must_be_safe_readable_local_file(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(Path, "home", return_value=Path(directory)):
            valid = Path(directory) / "tone.ogg"
            valid.write_bytes(b"audio")
            self.assertEqual(sp.resolve_sound(str(valid)), valid)
            for value in ("https://example.test/tone.wav", "bad\nname.wav", "/usr/bin/python3"):
                with self.subTest(value=value), self.assertRaisesRegex(sp.BridgeError, "Invalid sound file"):
                    sp.resolve_sound(value)
            large = Path(directory) / "large.wav"
            with large.open("wb") as stream:
                stream.truncate(sp.MAX_SOUND_SIZE + 1)
            with self.assertRaisesRegex(sp.BridgeError, "Invalid sound file"):
                sp.resolve_sound(str(large))

    def test_default_wav_is_small_valid_pcm(self):
        self.assertLess(sp.DEFAULT_SOUND.stat().st_size, 100_000)
        with wave.open(str(sp.DEFAULT_SOUND), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24_000)
            self.assertGreater(wav.getnframes(), 0)

    def test_token_file_and_env_url(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text(" secret\n", encoding="utf-8")
            token_path.chmod(0o600)
            env = {"SUPER_PRODUCTIVITY_TOKEN_FILE": str(token_path), "SUPER_PRODUCTIVITY_REST_URL": "http://localhost:9876/api/"}
            self.assertEqual(sp.read_token(env), "secret")
            self.assertEqual(sp.api_url(env), "http://localhost:9876/api")

    def test_exact_api_url_env_name(self):
        self.assertEqual(sp.api_url({"SUPERPRODUCTIVITY_API_URL": "http://127.0.0.1/"}), "http://127.0.0.1")

    def test_api_url_preserves_aliases_ports_paths_and_loopback_hosts(self):
        cases = [
            ("SUPERPRODUCTIVITY_API_URL", "http://localhost:3876/api", "http://localhost:3876/api"),
            ("SUPER_PRODUCTIVITY_REST_URL", "https://127.0.0.1:8443/rest/", "https://127.0.0.1:8443/rest"),
            ("SP_LOCAL_REST_URL", "http://[::1]:3876/v1", "http://[::1]:3876/v1"),
            ("SUPER_PRODUCTIVITY_URL", "http://localhost/custom", "http://localhost/custom"),
        ]
        for name, value, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(sp.api_url({name: value}), expected)

    def test_api_url_rejects_non_local_or_unsafe_values(self):
        rejected = [
            "ftp://localhost:3876",
            "http://example.com:3876",
            "http://127.0.0.2:3876",
            "http://localhost.example:3876",
            "http://user@localhost:3876",
            "http://user:password@127.0.0.1:3876",
            "http://localhost:3876/api#fragment",
            "http://localhost:3876/api#",
            "http://localhost:3876/api?token=secret",
            "http://localhost:3876/api?",
            "http://localhost:invalid",
            "not a URL",
        ]
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(sp.BridgeError):
                sp.api_url({"SUPERPRODUCTIVITY_API_URL": value})

    @mock.patch.object(sp, "read_token")
    def test_client_rejects_unsafe_url_before_reading_token(self, read_token):
        with self.assertRaisesRegex(sp.BridgeError, "loopback"):
            sp.Client("https://attacker.example/api")
        read_token.assert_not_called()

    def test_direct_env_token_override_does_not_require_a_file(self):
        env = {
            "SP_LOCAL_REST_TOKEN": " direct-secret ",
            "SUPER_PRODUCTIVITY_TOKEN_FILE": "/missing/token",
        }
        self.assertEqual(sp.read_token(env), "direct-secret")

    def test_token_file_rejects_group_and_world_permissions(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux token permission policy")
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text("secret", encoding="utf-8")
            for mode in (0o640, 0o604, 0o666):
                with self.subTest(mode=oct(mode)):
                    token_path.chmod(mode)
                    with self.assertRaisesRegex(sp.BridgeError, "group or world"):
                        sp.read_token({"SUPER_PRODUCTIVITY_TOKEN_FILE": str(token_path)})

    def test_token_file_rejects_wrong_owner(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux token ownership policy")
        fake_stat = mock.Mock(st_mode=0o100600, st_uid=os.geteuid() + 1)
        with mock.patch.object(Path, "lstat", return_value=fake_stat):
            with self.assertRaisesRegex(sp.BridgeError, "owned by the current user"):
                sp.read_token({"SUPER_PRODUCTIVITY_TOKEN_FILE": "/token"})

    def test_token_path_must_be_a_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(sp.BridgeError, "regular file"):
                sp.read_token({"SUPER_PRODUCTIVITY_TOKEN_FILE": directory})

    def test_token_path_must_not_be_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text("secret", encoding="utf-8")
            token_path.chmod(0o600)
            link_path = Path(directory) / "token-link"
            link_path.symlink_to(token_path)
            with self.assertRaisesRegex(sp.BridgeError, "regular file"):
                sp.read_token({"SUPER_PRODUCTIVITY_TOKEN_FILE": str(link_path)})

    def test_token_file_accepts_mode_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text("secret\n", encoding="utf-8")
            token_path.chmod(0o600)
            self.assertEqual(sp.read_token({"SUPER_PRODUCTIVITY_TOKEN_FILE": str(token_path)}), "secret")

    def test_token_sources_reject_oversized_values(self):
        with self.assertRaisesRegex(sp.BridgeError, "maximum size"):
            sp.read_token({"SP_LOCAL_REST_TOKEN": "x" * (sp.MAX_TOKEN_BYTES + 1)})
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_bytes(b"x" * (sp.MAX_TOKEN_BYTES + 1))
            token_path.chmod(0o600)
            with self.assertRaisesRegex(sp.BridgeError, "maximum size"):
                sp.read_token({"SUPER_PRODUCTIVITY_TOKEN_FILE": str(token_path)})

    @mock.patch.object(sp.urllib.request, "build_opener")
    def test_client_builds_proxyless_redirect_rejecting_opener(self, build_opener):
        sp.Client("http://127.0.0.1:3876", "secret")
        proxy_handler, redirect_handler = build_opener.call_args.args
        self.assertEqual(proxy_handler.proxies, {})
        self.assertIsInstance(redirect_handler, sp.RejectRedirects)

        request = sp.urllib.request.Request(
            "http://127.0.0.1:3876/tasks",
            headers={"Authorization": "Bearer secret"},
        )
        with self.assertRaises(sp.urllib.error.HTTPError) as raised:
            redirect_handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {"Location": "https://attacker.example/steal"},
                "https://attacker.example/steal",
            )
        raised.exception.close()
        build_opener.return_value.open.assert_not_called()

    def test_client_only_classifies_explicit_parsed_4xx_as_rejected(self):
        cases = [
            (400, b'{"ok":false,"error":{"message":"bad"}}', sp.RequestRejected),
            (422, b'{"error":"invalid"}', sp.RequestRejected),
            (400, b'not-json', sp.DispatchUnknown),
            (400, b'{"message":"not explicit"}', sp.DispatchUnknown),
            (500, b'{"ok":false,"error":"failed"}', sp.DispatchUnknown),
        ]
        for code, body, expected in cases:
            with self.subTest(code=code, body=body):
                error = sp.urllib.error.HTTPError("http://127.0.0.1/tasks", code, "error", {}, io.BytesIO(body))
                client = sp.Client("http://127.0.0.1", "")
                client.opener.open = mock.Mock(side_effect=error)
                with self.assertRaises(expected):
                    client.request("POST", "/tasks", {"title": "x"})

    def test_client_wraps_every_uncertain_transport_boundary(self):
        failures = [
            ConnectionResetError("reset"),
            sp.http.client.IncompleteRead(b"partial", 10),
            TimeoutError("timeout"),
            EOFError("closed"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                client = sp.Client("http://127.0.0.1", "")
                client.opener.open = mock.Mock(side_effect=failure)
                with self.assertRaises(sp.DispatchUnknown):
                    client.request("POST", "/tasks", {"title": "x"})

        unreadable = sp.urllib.error.HTTPError("http://127.0.0.1/tasks", 409, "error", {}, None)
        unreadable.read = mock.Mock(side_effect=ConnectionResetError("reset while reading error"))
        client = sp.Client("http://127.0.0.1", "")
        client.opener.open = mock.Mock(side_effect=unreadable)
        with self.assertRaises(sp.DispatchUnknown):
            client.request("POST", "/tasks", {"title": "x"})

    def test_success_status_failure_envelope_is_not_a_known_rejection(self):
        response = mock.MagicMock()
        response.read.return_value = b'{"ok":false,"error":"ambiguous"}'
        response.__enter__.return_value = response
        client = sp.Client("http://127.0.0.1", "")
        client.opener.open = mock.Mock(return_value=response)
        with self.assertRaises(sp.DispatchUnknown):
            client.request("POST", "/tasks", {"title": "x"})

    def test_client_rejects_oversized_success_and_error_bodies(self):
        response = mock.MagicMock()
        response.headers = {}
        response.read.return_value = b"x" * (sp.MAX_API_RESPONSE_BYTES + 1)
        response.__enter__.return_value = response
        client = sp.Client("http://127.0.0.1", "")
        client.opener.open = mock.Mock(return_value=response)
        with self.assertRaisesRegex(sp.DispatchUnknown, "maximum size"):
            client.request("GET", "/tasks")

        error = sp.urllib.error.HTTPError(
            "http://127.0.0.1/tasks", 500, "error", {},
            io.BytesIO(b"x" * (sp.MAX_API_RESPONSE_BYTES + 1)),
        )
        client.opener.open = mock.Mock(side_effect=error)
        with self.assertRaises(sp.DispatchUnknown):
            client.request("POST", "/tasks", {"title": "x"})

    def test_client_rejects_declared_oversized_body_before_read(self):
        response = mock.MagicMock()
        response.headers = {"Content-Length": str(sp.MAX_API_RESPONSE_BYTES + 1)}
        response.__enter__.return_value = response
        client = sp.Client("http://127.0.0.1", "")
        client.opener.open = mock.Mock(return_value=response)
        with self.assertRaisesRegex(sp.DispatchUnknown, "maximum size"):
            client.request("GET", "/tasks")
        response.read.assert_not_called()

    def test_mutation_lock_rejects_insecure_runtime_without_chmod(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux lock permission policy")
        with tempfile.TemporaryDirectory() as parent:
            runtime = Path(parent) / "runtime"
            runtime.mkdir(mode=0o755)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                with self.assertRaisesRegex(sp.BridgeError, "group or world"):
                    with sp.mutation_lock():
                        pass
            self.assertEqual(stat.S_IMODE(runtime.stat().st_mode), 0o755)

    def test_mutation_lock_rejects_runtime_and_lock_symlinks(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux lock symlink policy")
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            real_runtime = root / "real"
            real_runtime.mkdir(mode=0o700)
            runtime_link = root / "runtime-link"
            runtime_link.symlink_to(real_runtime, target_is_directory=True)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime_link)}):
                with self.assertRaisesRegex(sp.BridgeError, "not a symlink"):
                    with sp.mutation_lock():
                        pass

            target = root / "target"
            target.write_text("", encoding="utf-8")
            target.chmod(0o600)
            (real_runtime / "patrickfanella-superproductivity.lock").symlink_to(target)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(real_runtime)}):
                with self.assertRaisesRegex(sp.BridgeError, "securely open"):
                    with sp.mutation_lock():
                        pass

    def test_mutation_lock_rejects_existing_permissive_lock_file(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux lock permission policy")
        with tempfile.TemporaryDirectory() as parent:
            runtime = Path(parent) / "runtime"
            runtime.mkdir(mode=0o700)
            lock = runtime / "patrickfanella-superproductivity.lock"
            lock.write_text("", encoding="utf-8")
            lock.chmod(0o644)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                with self.assertRaisesRegex(sp.BridgeError, "group or world"):
                    with sp.mutation_lock():
                        pass
            self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o644)

    def test_default_token_path_uses_home_and_exact_case(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".config" / "superProductivity" / "local-rest-api-token"
            path.parent.mkdir(parents=True)
            path.write_text("default-secret\n", encoding="utf-8")
            path.chmod(0o600)
            with mock.patch.dict(os.environ, {"HOME": directory}, clear=True):
                self.assertEqual(sp.read_token(), "default-secret")

    def test_token_candidates_are_checked_in_priority_order(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            paths = [
                home / ".config/superProductivity/local-rest-api-token",
                home / ".var/app/com.super_productivity.SuperProductivity/config/superProductivity/local-rest-api-token",
                home / "snap/superproductivity/common/.config/superProductivity/local-rest-api-token",
                home / "snap/superproductivity/current/.config/superProductivity/local-rest-api-token",
            ]
            for index, path in enumerate(paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"secret-{index}", encoding="utf-8")
                path.chmod(0o600)
            with mock.patch.dict(os.environ, {"HOME": directory}, clear=True):
                self.assertEqual(sp.read_token(), "secret-0")
            paths[0].unlink()
            with mock.patch.dict(os.environ, {"HOME": directory}, clear=True):
                self.assertEqual(sp.read_token(), "secret-1")

    def test_discovers_flatpak_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".var/app/com.super_productivity.SuperProductivity/config/superProductivity/local-rest-api-token"
            path.parent.mkdir(parents=True)
            path.write_text("flatpak-secret", encoding="utf-8")
            path.chmod(0o600)
            with mock.patch.dict(os.environ, {"HOME": directory}, clear=True):
                self.assertEqual(sp.read_token(), "flatpak-secret")

    def test_discovers_snap_tokens_in_priority_order(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            common = home / "snap/superproductivity/common/.config/superProductivity/local-rest-api-token"
            current = home / "snap/superproductivity/current/.config/superProductivity/local-rest-api-token"
            for path, token in ((common, "common-secret"), (current, "current-secret")):
                path.parent.mkdir(parents=True)
                path.write_text(token, encoding="utf-8")
                path.chmod(0o600)
            with mock.patch.dict(os.environ, {"HOME": directory}, clear=True):
                self.assertEqual(sp.read_token(), "common-secret")
            common.unlink()
            with mock.patch.dict(os.environ, {"HOME": directory}, clear=True):
                self.assertEqual(sp.read_token(), "current-secret")

    def test_explicit_token_file_overrides_discovered_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            native = home / ".config/superProductivity/local-rest-api-token"
            explicit = home / "explicit-token"
            for path, token in ((native, "native-secret"), (explicit, "explicit-secret")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(token, encoding="utf-8")
                path.chmod(0o600)
            env = {"HOME": directory, "SUPER_PRODUCTIVITY_TOKEN_FILE": str(explicit)}
            self.assertEqual(sp.read_token(env), "explicit-secret")

    @mock.patch.object(sp.subprocess, "run")
    def test_show_focuses_existing_window(self, run):
        run.return_value.returncode = 0
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(sp.show()["ok"])
        self.assertEqual(run.call_args.args[0], ["hyprctl", "dispatch", "focuswindow", "title:^Super Productivity$"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(run.call_count, 1)

    @mock.patch.object(sp.subprocess, "run")
    def test_show_falls_back_to_launch_then_url(self, run):
        failed = mock.Mock(returncode=1)
        succeeded = mock.Mock(returncode=0)
        run.side_effect = [sp.subprocess.TimeoutExpired(["hyprctl"], 3), failed, succeeded]
        self.assertTrue(sp.show()["ok"])
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["hyprctl", "dispatch", "focuswindow", "title:^Super Productivity$"],
            ["gtk-launch", "superproductivity.desktop"],
            ["xdg-open", "superproductivity://"],
        ])
        self.assertTrue(all(call.kwargs["timeout"] == 3 for call in run.call_args_list))

    def test_main_writes_exactly_one_json_value_without_secret(self):
        stream = io.StringIO()
        with mock.patch.object(sp, "run", side_effect=sp.BridgeError("failed")), contextlib.redirect_stdout(stream):
            code = sp.main(["status"])
        lines = stream.getvalue().splitlines()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "failed"})

    def test_main_replaces_oversized_output_before_stdout(self):
        stream = io.StringIO()
        with (
            mock.patch.object(sp, "MAX_OUTPUT_BYTES", 100),
            mock.patch.object(sp, "run", return_value=({"ok": True, "data": "x" * 1000}, 0)),
            contextlib.redirect_stdout(stream),
        ):
            code = sp.main(["status"])
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(stream.getvalue()),
            {"ok": False, "error": "Bridge output exceeds the maximum size"},
        )


if __name__ == "__main__":
    unittest.main()
