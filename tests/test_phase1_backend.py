import importlib.util
import json
import signal
import subprocess
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "backend" / "superproductivity.py"
SPEC = importlib.util.spec_from_file_location("superproductivity_phase1", MODULE_PATH)
assert SPEC and SPEC.loader
sp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sp)


def task(task_id, **values):
    return {
        "id": task_id,
        "title": values.pop("title", task_id),
        "timeEstimate": values.pop("timeEstimate", 60_000),
        "timeSpent": values.pop("timeSpent", 0),
        "subTaskIds": values.pop("subTaskIds", []),
        "isDone": values.pop("isDone", False),
        **values,
    }


class StatefulAPI:
    def __init__(self, tasks, current=None, today=None):
        self.tasks = {value["id"]: dict(value) for value in tasks}
        self.current = current
        self.today = list(today if today is not None else self.tasks)
        self.calls = []
        self.failures = {}
        self.upstream_after_complete = None
        self.external_after_create = None
        self.final_estimate = None

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        failure = self.failures.pop((method, path), None)
        if failure:
            raise failure
        if method == "GET" and path == "/task-control/current":
            return None if self.current is None else self.tasks.get(self.current, {"id": self.current})
        if method == "GET" and path == "/tasks?tagId=TODAY":
            return [dict(self.tasks[value]) for value in self.today if value in self.tasks]
        if method == "GET" and path == "/tasks?includeDone=true":
            return [dict(value) for value in self.tasks.values()]
        if method == "GET" and path == "/tasks":
            return [dict(value) for value in self.tasks.values()]
        if method == "GET" and path == "/projects":
            return [{"id": "work", "title": "Work"}]
        if method == "GET" and path == "/tags":
            return []
        if method == "GET" and path.startswith("/tasks/"):
            task_id = sp.urllib.parse.unquote(path.split("/tasks/", 1)[1])
            value = dict(self.tasks[task_id])
            if self.final_estimate is not None and any(call[0] == "PATCH" for call in self.calls[:-1]):
                value["timeEstimate"] = self.final_estimate
            return value
        if method == "POST" and path == "/task-control/current":
            requested = body["taskId"]
            requested_task = self.tasks[requested]
            children = requested_task.get("subTaskIds", [])
            self.current = next((value for value in children if not self.tasks[value].get("isDone")), requested)
            return {}
        if method == "POST" and path == "/task-control/stop":
            self.current = None
            return {}
        if method == "PATCH" and path.startswith("/tasks/"):
            task_id = sp.urllib.parse.unquote(path.split("/tasks/", 1)[1])
            self.tasks[task_id].update(body)
            if body.get("isDone") is True and self.current == task_id:
                self.current = self.upstream_after_complete
            return dict(self.tasks[task_id])
        if method == "POST" and path == "/tasks":
            created = task("created", **body)
            self.tasks["created"] = created
            if self.external_after_create is not None:
                self.current = self.external_after_create
            return dict(created)
        raise AssertionError((method, path, body))


class PhaseOneBackendTests(unittest.TestCase):
    def test_chronological_hierarchy_matches_shared_fixture_without_mutation(self):
        fixture_path = Path(__file__).with_name("chronological-hierarchy.json")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        before = json.dumps(fixture["tasks"], sort_keys=True)
        ordered = sp.chronological_hierarchy(fixture["tasks"])
        self.assertEqual([value["id"] for value in ordered], fixture["expectedIds"])
        self.assertEqual(json.dumps(fixture["tasks"], sort_keys=True), before)
        self.assertEqual(next(value for value in ordered if value["id"] == "orphan-late")["depth"], 0)
        self.assertEqual(sp._auto_next_candidate(ordered, "early-child", 100), "tie-first")

    def test_empty_parent_id_is_canonical_top_level(self):
        normalized = sp.normalize_task(task("top", parentId=""))
        self.assertIsNone(normalized["parentId"])
        with self.assertRaisesRegex(sp.BridgeError, "malformed task"):
            sp.normalize_task(task("bad", parentId="line\nbreak"))

    def test_auto_next_prefers_authoritative_sibling_before_next_block(self):
        ordered = sp.chronological_hierarchy([
            task("later", dueWithTime=20),
            task("parent", dueWithTime=10, subTaskIds=["first", "second"]),
            task("first", parentId="parent"),
            task("second", parentId="parent", dueWithTime=10),
        ])
        self.assertEqual(sp._auto_next_candidate(ordered, "first", 10), "second")

    def test_auto_next_child_inherits_immediate_parent_schedule(self):
        now = 10_000
        ordered = sp.chronological_hierarchy([
            task("parent", dueWithTime=now, subTaskIds=["first", "second"]),
            task("first", parentId="parent"),
            task("second", parentId="parent"),
        ])
        self.assertEqual(sp._auto_next_candidate(ordered, "first", now, 1), "second")
        ordered[2]["dueWithTime"] = now + 2
        self.assertIsNone(sp._auto_next_candidate(ordered, "first", now, 1))
        ordered[0]["dueWithTime"] = None
        ordered[2]["dueWithTime"] = None
        self.assertIsNone(sp._auto_next_candidate(ordered, "first", now, 1))

    def test_auto_next_window_boundaries_and_candidate_order(self):
        now = 10_000_000
        window = 30 * 60_000
        ordered = [
            task("parent", depth=0, subTaskIds=["first", "bad", "sibling"]),
            task("first", depth=1, parentId="parent", dueWithTime=now),
            task("bad", depth=1, parentId="parent", dueWithTime=now + window + 1),
            task("sibling", depth=1, parentId="parent", dueWithTime=now - window),
            task("next-block", depth=0, dueWithTime=now + window),
            task("outside", depth=0, dueWithTime=now - window - 1),
        ]
        self.assertEqual(sp._auto_next_candidate(ordered, "first", now, window), "sibling")
        ordered[3]["isDone"] = True
        self.assertEqual(sp._auto_next_candidate(ordered, "first", now, window), "next-block")
        ordered[4]["dueWithTime"] = now + window + 1
        self.assertIsNone(sp._auto_next_candidate(ordered, "first", now, window))

    def test_auto_next_excludes_non_runnable_candidates_and_never_wraps(self):
        now = 1_000_000
        invalid = [
            task("target", depth=0, dueWithTime=now),
            task("unscheduled", depth=0),
            task("nan", depth=0, dueWithTime=float("nan")),
            task("container", depth=0, dueWithTime=now, subTaskIds=["child"]),
            task("done", depth=0, dueWithTime=now, isDone=True),
            task("eligible", depth=0, dueWithTime=now),
        ]
        self.assertEqual(sp._auto_next_candidate(invalid, "target", now, 1), "eligible")
        self.assertIsNone(sp._auto_next_candidate(invalid, "eligible", now, 1))

    def test_hierarchy_rules_and_retained_fields(self):
        values = [
            task("p", title="Parent", subTaskIds=["c", "missing"]),
            task("q", subTaskIds=["c"]),
            task("c", parentId="p", projectId="work", dueDay="2026-08-24", dueWithTime=1234),
            task("orphan", parentId="gone"),
            task("bad", subTaskIds="bad"),
            task("c", title="duplicate"),
        ]
        flattened, warnings = sp.build_hierarchy(values, {"work": "Work"})
        self.assertEqual([value["id"] for value in flattened], ["p", "c", "q", "orphan", "bad"])
        child = flattened[1]
        self.assertEqual((child["depth"], child["parentTitle"], child["projectTitle"]), (1, "Parent", "Work"))
        self.assertEqual(flattened[0]["subTaskIds"], ["c", "missing"])
        self.assertTrue({"missing-child", "conflicting-parent", "missing-parent", "malformed-child-list", "duplicate-task-id"}.issubset(warnings))

    def test_status_context_failures_do_not_hide_valid_current(self):
        api = StatefulAPI([task("current", timeEstimate=100, timeSpent=150)], current="current")
        api.failures[("GET", "/tasks?tagId=TODAY")] = sp.DispatchUnknown("today down")
        api.failures[("GET", "/projects")] = sp.RequestRejected("projects down")
        result = sp.status(api)
        self.assertEqual(result["task"]["id"], "current")
        self.assertEqual(result["signedRemainingMs"], -50)
        self.assertEqual(result["overtimeMs"], 50)
        self.assertEqual(result["context"], {
            "todayOk": False,
            "projectsOk": False,
            "tasksOk": True,
            "warnings": ["today-unavailable", "projects-unavailable"],
        })
        self.assertIsNone(result["scheduledTasks"])
        self.assertIsNone(result["todayFetchedAt"])
        self.assertEqual(api.calls[-1][1], "/task-control/current")

    def test_dispatch_timeout_is_unknown_and_not_retried(self):
        api = StatefulAPI([task("one")])
        api.failures[("POST", "/task-control/current")] = sp.DispatchUnknown("timeout")
        result = sp.start(api, "one")
        self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("unknown", "dispatch", None))
        self.assertEqual(sum(call[:2] == ("POST", "/task-control/current") for call in api.calls), 1)

    def test_parsed_http_failure_is_known_not_applied(self):
        api = StatefulAPI([task("one")])
        api.failures[("POST", "/task-control/current")] = sp.RequestRejected("bad request")
        result = sp.start(api, "one")
        self.assertEqual((result["state"], result["mutationApplied"]), ("failed", False))

    def test_stop_preflight_conflict_and_external_switch(self):
        conflict = StatefulAPI([task("wanted"), task("other")], current="other")
        result = sp.stop(conflict, "wanted")
        self.assertEqual((result["state"], result["stage"]), ("conflict", "preflight"))
        self.assertFalse(any(call[0] == "POST" for call in conflict.calls))

        switched = StatefulAPI([task("wanted"), task("other")], current="wanted")
        original = switched.request
        def request(method, path, body=None):
            value = original(method, path, body)
            if method == "POST":
                switched.current = "other"
            return value
        switched.request = request
        result = sp.stop(switched, "wanted")
        self.assertEqual((result["state"], result["finalCurrentId"], result["raceDetected"]), ("partial", "other", True))

    def test_malformed_current_never_behaves_like_no_current(self):
        malformed = []

        stop_api = StatefulAPI([task("wanted")], current="wanted")
        stop_original = stop_api.request
        stop_api.request = lambda method, path, body=None: malformed if path == "/task-control/current" else stop_original(method, path, body)
        stopped = sp.stop(stop_api, "wanted")
        self.assertEqual((stopped["state"], stopped["stage"], stopped["mutationApplied"]), ("failed", "preflight", False))
        self.assertFalse(any(call[0] == "POST" for call in stop_api.calls))

        add_api = StatefulAPI([task("old")], current="old")
        add_original = add_api.request
        add_api.request = lambda method, path, body=None: malformed if path == "/task-control/current" else add_original(method, path, body)
        added = sp.add(add_api, "Created", True)
        self.assertEqual((added["state"], added["stage"], added["mutationApplied"]), ("failed", "preflight", False))
        self.assertFalse(any(call[0] == "POST" for call in add_api.calls))

        start_api = StatefulAPI([task("wanted")])
        start_original = start_api.request
        def malformed_start_verify(method, path, body=None):
            if path == "/task-control/current":
                start_api.calls.append((method, path, body))
                return malformed
            return start_original(method, path, body)
        start_api.request = malformed_start_verify
        started = sp.start(start_api, "wanted")
        self.assertEqual((started["state"], started["stage"], started["mutationApplied"]), ("unknown", "verify", True))

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_malformed_current_after_completion_is_partial(self, _sleep):
        api = StatefulAPI([task("first"), task("next")], current="first")
        original = api.request
        current_reads = 0
        def malformed_after_completion(method, path, body=None):
            nonlocal current_reads
            if path == "/task-control/current":
                current_reads += 1
                if current_reads > 2:
                    api.calls.append((method, path, body))
                    return {"id": 7}
            return original(method, path, body)
        api.request = malformed_after_completion

        result = sp.complete(api, "first", True)

        self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("partial", "followup-preflight", True))
        self.assertEqual(result["autoNext"], "current-unknown")

    def test_start_parent_child_matrix_and_url_encoding(self):
        values = [task("parent / id", subTaskIds=["done", "child"]), task("done", parentId="parent / id", isDone=True), task("child", parentId="parent / id")]
        api = StatefulAPI(values)
        result = sp.start(api, "parent / id")
        self.assertEqual((result["state"], result["actualTaskId"]), ("succeeded", "child"))
        self.assertEqual(api.calls[0][1], "/tasks/parent%20%2F%20id")

        direct = StatefulAPI(values)
        self.assertEqual(sp.start(direct, "child")["finalCurrentId"], "child")
        all_done = StatefulAPI([task("p", subTaskIds=["done"]), task("done", parentId="p", isDone=True)])
        self.assertEqual(sp.start(all_done, "p")["state"], "conflict")
        missing = StatefulAPI([task("p", subTaskIds=["missing"])])
        self.assertEqual(sp.start(missing, "p")["state"], "conflict")

    def test_current_parent_completion_rejects_retained_children_even_when_done(self):
        for child_values in ([], [task("c", parentId="p")], [task("c", parentId="p", isDone=True)]):
            with self.subTest(child_values=child_values):
                api = StatefulAPI([task("p", subTaskIds=["c"]), *child_values], current="p")
                result = sp.complete(api, "p")
                self.assertEqual(result["state"], "conflict")
                self.assertIn("retains subtasks", result["message"].casefold())
                self.assertFalse(any(call[0] == "PATCH" for call in api.calls))
                self.assertNotIn(("GET", "/tasks?includeDone=true", None), api.calls)

    def test_parent_completion_rejects_duplicate_and_malformed_authoritative_children(self):
        cases = [
            (task("p", subTaskIds=["c", "c"]), [task("c", parentId="p", isDone=True)]),
            (task("p", subTaskIds=["c"]), [task("c", parentId="p", isDone=True), task("c", title="later", parentId="p", isDone=True)]),
            (task("p", subTaskIds=["c"]), [{"id": "c", "isDone": True}]),
        ]
        for parent, authoritative in cases:
            with self.subTest(authoritative=authoritative):
                api = StatefulAPI([parent, task("c", parentId="p", isDone=True)], current="p")
                original = api.request
                def request(method, path, body=None):
                    if path == "/tasks?includeDone=true":
                        api.calls.append((method, path, body))
                        return authoritative
                    return original(method, path, body)
                api.request = request
                result = sp.complete(api, "p")
                self.assertEqual((result["state"], result["stage"]), ("conflict", "preflight"))
                self.assertFalse(any(call[0] == "PATCH" for call in api.calls))

    def test_completion_rejects_malformed_or_mismatched_target_without_side_effects(self):
        for target_payload in ({"id": "p", "title": 7}, task("different")):
            with self.subTest(target_payload=target_payload):
                api = StatefulAPI([task("p"), task("next")], current="p")
                original = api.request

                def target_read(method, path, body=None):
                    if method == "GET" and path == "/tasks/p":
                        api.calls.append((method, path, body))
                        return target_payload
                    return original(method, path, body)

                api.request = target_read
                result = sp.complete(api, "p", True)

                self.assertEqual((result["stage"], result["mutationApplied"], result["autoNext"]), ("preflight", False, "not-run"))
                self.assertFalse(any(call[0] in {"PATCH", "POST"} for call in api.calls))

    def test_completion_rejects_conflicting_child_ownership_without_side_effects(self):
        values = [
            task("p", subTaskIds=["child"]),
            task("child", parentId="p", isDone=True),
            task("other", subTaskIds=["child"]),
            task("next"),
        ]
        api = StatefulAPI(values, current="p")

        result = sp.complete(api, "p", True)

        self.assertEqual((result["state"], result["stage"], result["autoNext"]), ("conflict", "preflight", "not-run"))
        self.assertIn("retains subtasks", result["message"].casefold())
        self.assertFalse(any(call[0] in {"PATCH", "POST"} for call in api.calls))

    @mock.patch.object(sp.time, "sleep")
    def test_completion_rejects_mismatched_done_readback_before_auto_next(self, sleep):
        api = StatefulAPI([task("p"), task("next")], current="p")
        original = api.request
        target_reads = 0

        def mismatched_readback(method, path, body=None):
            nonlocal target_reads
            if method == "GET" and path == "/tasks/p":
                target_reads += 1
                if target_reads == 2:
                    api.calls.append((method, path, body))
                    return task("different", isDone=True)
            return original(method, path, body)

        api.request = mismatched_readback
        result = sp.complete(api, "p", True)

        self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("partial", "verify", True))
        self.assertEqual(result["autoNext"], "not-run")
        self.assertEqual(sum(call[0] == "PATCH" for call in api.calls), 1)
        self.assertFalse(any(call[:2] == ("POST", "/task-control/current") for call in api.calls))
        sleep.assert_not_called()

    def test_list_completion_accepts_noncurrent_and_does_not_inspect_unrelated_current_change(self):
        api = StatefulAPI([task("listed"), task("current"), task("external")], current="current")
        original = api.request
        def switch_after_patch(method, path, body=None):
            value = original(method, path, body)
            if method == "PATCH":
                api.current = "external"
            return value
        api.request = switch_after_patch

        result = sp.complete_listed_task(api, "listed")

        self.assertEqual((result["state"], result["kind"], result["mutationApplied"]), ("succeeded", "complete-list", True))
        self.assertTrue(api.tasks["listed"]["isDone"])
        self.assertEqual(sum(call[0] == "PATCH" for call in api.calls), 1)
        self.assertEqual(sum(call[:2] == ("GET", "/task-control/current") for call in api.calls), 1)

    def test_list_completion_leaf_skips_bulk_task_read(self):
        api = StatefulAPI([task("listed", subTaskIds=[])])

        result = sp.complete_listed_task(api, "listed")

        self.assertEqual(result["state"], "succeeded")
        self.assertNotIn(("GET", "/tasks?includeDone=true", None), api.calls)

    def test_list_completion_rejects_container_without_bulk_read(self):
        for payload in (sp.DispatchUnknown("bulk down"), {}):
            with self.subTest(payload=payload):
                api = StatefulAPI([task("listed", subTaskIds=["child"]), task("child", parentId="listed", isDone=True)])
                if isinstance(payload, Exception):
                    api.failures[("GET", "/tasks?includeDone=true")] = payload
                else:
                    original = api.request
                    api.request = lambda method, path, body=None: payload if path == "/tasks?includeDone=true" else original(method, path, body)
                result = sp.complete_listed_task(api, "listed")
                self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("conflict", "preflight", False))
                self.assertFalse(any(call[0] == "PATCH" for call in api.calls))
                self.assertNotIn(("GET", "/tasks?includeDone=true", None), api.calls)

    def test_list_completion_current_postconditions(self):
        cleared = StatefulAPI([task("listed")], current="listed")
        self.assertEqual(sp.complete_listed_task(cleared, "listed")["state"], "succeeded")

        remains = StatefulAPI([task("listed")], current="listed")
        remains.upstream_after_complete = "listed"
        result = sp.complete_listed_task(remains, "listed")
        self.assertEqual((result["state"], result["raceDetected"], result["finalCurrentId"]), ("partial", True, "listed"))

        switched = StatefulAPI([task("listed"), task("other")], current="listed")
        switched.upstream_after_complete = "other"
        result = sp.complete_listed_task(switched, "listed")
        self.assertEqual((result["state"], result["finalCurrentId"]), ("succeeded", "other"))

    def test_list_completion_rejects_done_or_malformed_fresh_target(self):
        done = StatefulAPI([task("listed", isDone=True)])
        self.assertEqual(sp.complete_listed_task(done, "listed")["state"], "conflict")

        malformed = StatefulAPI([task("listed")])
        original = malformed.request
        def malformed_target(method, path, body=None):
            if path == "/tasks/listed":
                malformed.calls.append((method, path, body))
                return {"id": "listed", "title": 7}
            return original(method, path, body)
        malformed.request = malformed_target
        self.assertEqual(sp.complete_listed_task(malformed, "listed")["state"], "failed")
        self.assertFalse(any(call[0] == "PATCH" for call in malformed.calls))

    def test_list_completion_rejects_malformed_subtask_ids_before_patch(self):
        cases = (
            (None, "failed"),
            ("child", "failed"),
            (["child", "child"], "conflict"),
            (["bad\nchild"], "failed"),
        )
        for child_ids, expected_state in cases:
            with self.subTest(child_ids=child_ids):
                api = StatefulAPI([task("listed", subTaskIds=child_ids)])

                result = sp.complete_listed_task(api, "listed")

                self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), (expected_state, "preflight", False))
                self.assertFalse(any(call[0] == "PATCH" for call in api.calls))

    def test_list_completion_malformed_verification_cannot_succeed(self):
        api = StatefulAPI([task("listed")])
        original = api.request
        target_reads = 0

        def malformed_readback(method, path, body=None):
            nonlocal target_reads
            value = original(method, path, body)
            if method == "GET" and path == "/tasks/listed":
                target_reads += 1
                if target_reads == 2:
                    value["subTaskIds"] = "malformed"
            return value

        api.request = malformed_readback

        result = sp.complete_listed_task(api, "listed")

        self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("unknown", "verify", True))
        self.assertEqual(sum(call[0] == "PATCH" for call in api.calls), 1)

    def test_list_completion_rejects_target_and_authoritative_child_edge_cases(self):
        cases = [
            ([task("listed", subTaskIds=["child", "child"]), task("child", parentId="listed", isDone=True)], "Duplicate"),
            ([task("listed", subTaskIds=["missing"])], "Missing"),
            ([task("listed", subTaskIds=["child"]), {"id": "child", "isDone": True}], "Malformed"),
            ([task("listed", subTaskIds=["child"]), task("child", parentId="other", isDone=True)], "Conflicting"),
            ([task("listed", subTaskIds=["child"]), task("child", parentId="listed")], "Unfinished"),
            ([task("listed", subTaskIds=["child"]), task("child", parentId="listed", isDone=True), task("other", subTaskIds=["child"])], "ownership"),
        ]
        for values, message in cases:
            with self.subTest(message=message):
                api = StatefulAPI([value for value in values if "title" in value], current="current")
                authoritative = values
                original = api.request
                def request(method, path, body=None):
                    if path == "/tasks?includeDone=true":
                        api.calls.append((method, path, body))
                        return authoritative
                    return original(method, path, body)
                api.request = request
                result = sp.complete_listed_task(api, "listed")
                self.assertEqual((result["state"], result["stage"]), ("conflict", "preflight"))
                self.assertIn("retains subtasks", result["message"].casefold())
                self.assertFalse(any(call[0] == "PATCH" for call in api.calls))

    def test_list_completion_ignores_unrelated_malformed_and_rejects_duplicate_child_ids(self):
        api = StatefulAPI([task("listed", subTaskIds=["child"]), task("child", parentId="listed", isDone=True)])
        original = api.request
        def request(method, path, body=None):
            if path == "/tasks?includeDone=true":
                api.calls.append((method, path, body))
                return [task("child", parentId="listed", isDone=True), "bad", {"id": "unrelated"}]
            return original(method, path, body)
        api.request = request
        self.assertEqual(sp.complete_listed_task(api, "listed")["state"], "conflict")

        duplicate = StatefulAPI([task("listed", subTaskIds=["child"]), task("child", parentId="listed", isDone=True)])
        duplicate_original = duplicate.request
        def duplicate_request(method, path, body=None):
            if path == "/tasks?includeDone=true":
                duplicate.calls.append((method, path, body))
                return [task("child", parentId="listed", isDone=True), task("child", parentId="listed", isDone=True)]
            return duplicate_original(method, path, body)
        duplicate.request = duplicate_request
        self.assertEqual(sp.complete_listed_task(duplicate, "listed")["state"], "conflict")

    def test_current_completion_rechecks_current_immediately_before_patch(self):
        for changed in (None, "other"):
            with self.subTest(changed=changed):
                api = StatefulAPI([task("listed"), task("other")], current="listed")
                original = api.request
                current_reads = 0

                def interleaved_current(method, path, body=None):
                    nonlocal current_reads
                    if method == "GET" and path == "/task-control/current":
                        current_reads += 1
                        if current_reads == 2:
                            api.calls.append((method, path, body))
                            return None if changed is None else dict(api.tasks[changed])
                    return original(method, path, body)

                api.request = interleaved_current
                result = sp.complete(api, "listed")

                self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("conflict", "preflight", False))
                self.assertTrue(result["raceDetected"])
                self.assertEqual(result["observedCurrentId"], changed)
                self.assertFalse(any(call[0] == "PATCH" for call in api.calls))

    def test_list_completion_unknown_patch_is_not_retried(self):
        api = StatefulAPI([task("listed")])
        api.failures[("PATCH", "/tasks/listed")] = sp.DispatchUnknown("timeout")
        result = sp.complete_listed_task(api, "listed")
        self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("unknown", "dispatch", None))
        self.assertEqual(sum(call[0] == "PATCH" for call in api.calls), 1)

    def test_complete_task_cli_dispatches_targeted_list_completion(self):
        with mock.patch.object(sp, "Client") as client, mock.patch.object(
            sp, "complete_listed_task", return_value={"state": "succeeded"}
        ) as complete_listed:
            result, code = sp.run(["complete-task", "exact-id"])
        self.assertEqual((result, code), ({"state": "succeeded"}, 0))
        complete_listed.assert_called_once_with(client.return_value, "exact-id")

    def test_complete_cli_auto_next_window_and_compatibility(self):
        with mock.patch.object(sp, "Client") as client, mock.patch.object(
            sp, "complete", return_value={"state": "succeeded"}
        ) as complete:
            sp.run(["complete", "task", "--auto-next"])
            complete.assert_called_once_with(client.return_value, "task", True, 30)
            complete.reset_mock()
            sp.run(["complete", "task", "--auto-next-window", "45", "--auto-next"])
            complete.assert_called_once_with(client.return_value, "task", True, 45)
        invalid = [
            ["complete", "task", "--auto-next-window", "30"],
            ["complete", "task", "--auto-next", "--auto-next"],
            ["complete", "task", "--auto-next", "--auto-next-window", "30", "--auto-next-window", "40"],
            ["complete", "task", "--auto-next", "--auto-next-window", "0"],
            ["complete", "task", "--auto-next", "--auto-next-window", "1441"],
            ["complete", "task", "--auto-next", "--auto-next-window", "1.5"],
            ["complete", "task", "--auto-next", "--auto-next-window", "NaN"],
        ]
        for argv in invalid:
            with self.subTest(argv=argv), self.assertRaises(sp.BridgeError):
                sp.run(argv)

    def test_every_mutator_structures_lock_setup_errors(self):
        calls = [
            ("add", lambda: sp.add(mock.Mock(), "Task")),
            ("start", lambda: sp.start(mock.Mock(), "task")),
            ("stop", lambda: sp.stop(mock.Mock(), "task")),
            ("complete", lambda: sp.complete(mock.Mock(), "task")),
            ("extend", lambda: sp.extend(mock.Mock(), "task", 5)),
        ]
        for kind, invoke in calls:
            with self.subTest(kind=kind), mock.patch.object(sp, "mutation_lock", side_effect=OSError("lock unavailable")):
                result = invoke()
                self.assertEqual((result["kind"], result["state"], result["stage"], result["mutationApplied"]), (kind, "failed", "preflight", False))

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_upstream_current_both_null_and_anchor(self, sleep):
        now = sp.time.time_ns() // 1_000_000
        values = [task("p", dueWithTime=now - 1, subTaskIds=["first", "second"]), task("first", parentId="p"), task("second", parentId="p", dueWithTime=now), task("later", dueWithTime=now)]
        upstream = StatefulAPI(values, current="first")
        upstream.upstream_after_complete = "later"
        result = sp.complete(upstream, "first", True)
        self.assertEqual(result["autoNext"], "skipped-upstream-current")
        sleep.assert_not_called()

        api = StatefulAPI(values, current="first")
        result = sp.complete(api, "first", True)
        self.assertEqual((result["state"], result["autoNext"], result["nextTaskId"]), ("succeeded", "started", "second"))
        sleep.assert_called_once_with(sp.AUTO_NEXT_GRACE)

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_excludes_hydrated_unscheduled_sibling(self, _sleep):
        values = [
            task("parent", subTaskIds=["first", "second"]),
            task("first", parentId="parent"),
            task("second", parentId="parent"),
            task("unrelated"),
        ]
        api = StatefulAPI(values, current="first", today=["parent", "first"])

        result = sp.complete(api, "first", True)

        self.assertEqual(result["autoNext"], "no-candidate")
        self.assertEqual(sum(call[:2] == ("GET", "/tasks?includeDone=true") for call in api.calls), 1)

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_excludes_unrelated_bulk_tasks(self, _sleep):
        api = StatefulAPI([task("first"), task("unrelated")], current="first", today=["first"])

        result = sp.complete(api, "first", True)

        self.assertEqual(result["autoNext"], "no-candidate")
        self.assertNotIn("nextTaskId", result)

    def test_auto_next_hydration_failure_fails_before_completion(self):
        values = [task("parent", subTaskIds=["first", "second"]), task("first", parentId="parent"), task("second", parentId="parent")]
        api = StatefulAPI(values, current="first", today=["parent", "first"])
        api.failures[("GET", "/tasks?includeDone=true")] = sp.DispatchUnknown("bulk down")

        result = sp.complete(api, "first", True)

        self.assertEqual((result["state"], result["stage"], result["mutationApplied"]), ("failed", "preflight", False))
        self.assertFalse(any(call[0] == "PATCH" for call in api.calls))

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_candidate_stale_and_followup_unknown(self, _sleep):
        now = sp.time.time_ns() // 1_000_000
        values = [task("first", dueWithTime=now - 1), task("next", dueWithTime=now)]
        stale = StatefulAPI(values, current="first")
        original = stale.request
        reads = 0
        def stale_request(method, path, body=None):
            nonlocal reads
            if method == "GET" and path == "/tasks/next":
                reads += 1
                stale.tasks["next"]["isDone"] = True
            return original(method, path, body)
        stale.request = stale_request
        result = sp.complete(stale, "first", True)
        self.assertEqual((result["state"], result["autoNext"]), ("succeeded", "skipped-candidate"))

        unknown = StatefulAPI(values, current="first")
        original_unknown = unknown.request
        def unknown_request(method, path, body=None):
            if method == "POST" and path == "/task-control/current":
                raise sp.DispatchUnknown("timeout")
            return original_unknown(method, path, body)
        unknown.request = unknown_request
        result = sp.complete(unknown, "first", True)
        self.assertEqual((result["state"], result["stage"], result["followupMutationApplied"]), ("unknown", "followup-dispatch", None))

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_revalidates_window_and_checks_current_third_time(self, _sleep):
        now = 1_000_000
        distant = StatefulAPI([task("first", dueWithTime=now - 1), task("next", dueWithTime=now)], current="first")
        with mock.patch.object(sp.time, "time_ns", side_effect=[now * 1_000_000, (now + 60_001) * 1_000_000]):
            result = sp.complete(distant, "first", True, 1)
        self.assertEqual((result["state"], result["autoNext"], result["followupMutationApplied"]), ("succeeded", "skipped-candidate", False))
        self.assertFalse(any(call[:2] == ("POST", "/task-control/current") for call in distant.calls))

        raced = StatefulAPI([task("first", dueWithTime=now - 1), task("next", dueWithTime=now), task("external")], current="first")
        original = raced.request
        def switch_after_candidate(method, path, body=None):
            value = original(method, path, body)
            if method == "GET" and path == "/tasks/next":
                raced.current = "external"
            return value
        raced.request = switch_after_candidate
        with mock.patch.object(sp.time, "time_ns", return_value=now * 1_000_000):
            result = sp.complete(raced, "first", True, 1)
        self.assertEqual((result["state"], result["autoNext"], result["finalCurrentId"]), ("succeeded", "skipped-upstream-current", "external"))
        candidate_read = raced.calls.index(("GET", "/tasks/next", None))
        self.assertEqual(raced.calls[candidate_read + 1], ("GET", "/task-control/current", None))
        self.assertFalse(any(call[:2] == ("POST", "/task-control/current") for call in raced.calls))

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_malformed_or_mismatched_candidate_never_starts(self, _sleep):
        now = sp.time.time_ns() // 1_000_000
        for candidate_payload, expected in (
            ({}, ("partial", "followup-preflight", "candidate-unknown")),
            (task("different", dueWithTime=now), ("succeeded", "done", "skipped-candidate")),
            (task("next", subTaskIds=["child"], dueWithTime=now), ("succeeded", "done", "skipped-candidate")),
        ):
            with self.subTest(candidate_payload=candidate_payload):
                api = StatefulAPI([task("first", dueWithTime=now - 1), task("next", dueWithTime=now)], current="first")
                original = api.request
                def candidate_read(method, path, body=None):
                    if method == "GET" and path == "/tasks/next":
                        api.calls.append((method, path, body))
                        return candidate_payload
                    return original(method, path, body)
                api.request = candidate_read

                result = sp.complete(api, "first", True)

                self.assertEqual((result["state"], result["stage"], result["autoNext"]), expected)
                self.assertFalse(any(call[:2] == ("POST", "/task-control/current") for call in api.calls))

    @mock.patch.object(sp.time, "sleep")
    def test_completion_parent_grace_matrix_and_unrelated_current_wins(self, sleep):
        now = sp.time.time_ns() // 1_000_000
        values = [
            task("parent", subTaskIds=["first", "next"]),
            task("first", parentId="parent"),
            task("next", parentId="parent", dueWithTime=now),
            task("other"),
        ]
        for sequence, expected in (
            (["parent", "parent", "parent"], ("started", "next")),
            ([None, "parent", "parent"], ("started", "next")),
            (["parent", None, None], ("started", "next")),
            (["parent", "other"], ("skipped-upstream-current", "other")),
        ):
            with self.subTest(sequence=sequence):
                api = StatefulAPI(values, current="first")
                api.upstream_after_complete = "parent"
                original = api.request
                post_reads = iter(sequence)
                current_reads = 0

                def sequenced(method, path, body=None):
                    nonlocal current_reads
                    if method == "GET" and path == "/task-control/current":
                        current_reads += 1
                        if current_reads > 2:
                            try:
                                value = next(post_reads)
                            except StopIteration:
                                return original(method, path, body)
                            api.calls.append((method, path, body))
                            return None if value is None else dict(api.tasks[value])
                    return original(method, path, body)

                api.request = sequenced
                result = sp.complete(api, "first", True)
                self.assertEqual((result["autoNext"], result["finalCurrentId"]), expected)
                followups = [call for call in api.calls if call[0] == "POST"]
                self.assertLessEqual(len(followups), 1)
        self.assertEqual(sleep.call_count, 4)

    @mock.patch.object(sp.time, "sleep")
    def test_no_candidate_corrects_exact_parent_enabled_and_disabled(self, _sleep):
        values = [task("parent", subTaskIds=["first"]), task("first", parentId="parent")]
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                api = StatefulAPI(values, current="first")
                api.upstream_after_complete = "parent"
                result = sp.complete(api, "first", enabled)
                self.assertEqual((result["state"], result["autoNext"], result["finalCurrentId"]),
                                 ("succeeded", "parent-corrected", None))
                self.assertEqual(sum(call[:2] == ("POST", "/task-control/stop") for call in api.calls), 1)
                stop_index = api.calls.index(("POST", "/task-control/stop", None))
                self.assertEqual(api.calls[stop_index - 1], ("GET", "/task-control/current", None))

    @mock.patch.object(sp.time, "sleep")
    def test_stale_candidate_corrects_parent_but_candidate_uncertainty_does_not(self, _sleep):
        now = sp.time.time_ns() // 1_000_000
        values = [task("parent", subTaskIds=["first", "next"]), task("first", parentId="parent"),
                  task("next", parentId="parent", dueWithTime=now)]
        stale = StatefulAPI(values, current="first")
        stale.upstream_after_complete = "parent"
        original = stale.request

        def done_candidate(method, path, body=None):
            if method == "GET" and path == "/tasks/next":
                stale.tasks["next"]["isDone"] = True
            return original(method, path, body)

        stale.request = done_candidate
        result = sp.complete(stale, "first", True)
        self.assertEqual((result["state"], result["autoNext"]), ("succeeded", "parent-corrected"))
        self.assertEqual(sum(call[0] == "POST" for call in stale.calls), 1)

        missing = StatefulAPI(values, current="first")
        missing.upstream_after_complete = "parent"
        missing.failures[("GET", "/tasks/next")] = sp.RequestRejected("not found")
        result = sp.complete(missing, "first", True)
        self.assertEqual((result["state"], result["autoNext"]), ("succeeded", "parent-corrected"))
        self.assertEqual(sum(call[:2] == ("POST", "/task-control/stop") for call in missing.calls), 1)

        uncertain = StatefulAPI(values, current="first")
        uncertain.upstream_after_complete = "parent"
        uncertain.failures[("GET", "/tasks/next")] = sp.DispatchUnknown("candidate unavailable")
        result = sp.complete(uncertain, "first", True)
        self.assertEqual((result["state"], result["autoNext"]), ("partial", "candidate-unknown"))
        self.assertFalse(any(call[0] == "POST" for call in uncertain.calls))

    @mock.patch.object(sp.time, "sleep")
    def test_parent_stop_failure_matrix_has_one_followup_and_no_retry(self, _sleep):
        values = [task("parent", subTaskIds=["first"]), task("first", parentId="parent"), task("other")]
        cases = (
            (sp.RequestRejected("rejected"), ("partial", "followup-dispatch", False)),
            (sp.DispatchUnknown("timeout"), ("unknown", "followup-dispatch", None)),
        )
        for failure, expected in cases:
            with self.subTest(failure=failure):
                api = StatefulAPI(values, current="first")
                api.upstream_after_complete = "parent"
                api.failures[("POST", "/task-control/stop")] = failure
                result = sp.complete(api, "first")
                self.assertEqual((result["state"], result["stage"], result["followupMutationApplied"]), expected)
                self.assertEqual(sum(call[:2] == ("POST", "/task-control/stop") for call in api.calls), 1)

        for malformed in (True, False):
            with self.subTest(malformed=malformed):
                api = StatefulAPI(values, current="first")
                api.upstream_after_complete = "parent"
                original = api.request
                stop_sent = False

                def bad_verify(method, path, body=None):
                    nonlocal stop_sent
                    value = original(method, path, body)
                    if method == "POST" and path == "/task-control/stop":
                        stop_sent = True
                    elif stop_sent and method == "GET" and path == "/task-control/current":
                        return {"id": 7} if malformed else dict(api.tasks["other"])
                    return value

                api.request = bad_verify
                result = sp.complete(api, "first")
                expected = ("unknown", "followup-verify", None) if malformed else ("partial", "followup-verify", True)
                self.assertEqual((result["state"], result["stage"], result["followupMutationApplied"]), expected)
                self.assertEqual(sum(call[:2] == ("POST", "/task-control/stop") for call in api.calls), 1)

    def test_extend_validation_and_final_mismatch(self):
        api = StatefulAPI([task("one", timeEstimate=1000)], current="one")
        api.final_estimate = 999
        result = sp.extend(api, "one", 5)
        self.assertEqual((result["state"], result["oldEstimate"], result["intendedEstimate"], result["finalEstimate"]), ("partial", 1000, 301000, 999))
        self.assertTrue(result["raceDetected"])
        for minutes in (0, 1441, 1.5, "2"):
            self.assertEqual(sp.extend(api, "one", minutes)["stage"], "validation")
        huge = StatefulAPI([task("one", timeEstimate=sp.MAX_ESTIMATE_MS)], current="one")
        self.assertEqual(sp.extend(huge, "one", 1)["state"], "failed")

    def test_add_and_switch_preserves_created_task_on_external_switch(self):
        api = StatefulAPI([task("old"), task("external")], current="old")
        api.external_after_create = "external"
        result = sp.add(api, "Created", True)
        self.assertEqual((result["state"], result["mutationApplied"], result["followupMutationApplied"]), ("partial", True, False))
        self.assertIn("created", api.tasks)
        self.assertFalse(any(call[0] == "POST" and call[1] == "/task-control/current" for call in api.calls))

    def test_add_and_switch_rechecks_after_created_task_read(self):
        api = StatefulAPI([task("old"), task("external")], current="old")
        original = api.request
        def interleaved(method, path, body=None):
            value = original(method, path, body)
            if method == "GET" and path == "/tasks/created":
                api.current = "external"
            return value
        api.request = interleaved
        result = sp.add(api, "Created", True)
        self.assertEqual((result["state"], result["followupMutationApplied"], result["finalCurrentId"]), ("partial", False, "external"))
        created_read = api.calls.index(("GET", "/tasks/created", None))
        self.assertEqual(api.calls[created_read + 1], ("GET", "/task-control/current", None))
        self.assertFalse(any(call[0] == "POST" and call[1] == "/task-control/current" for call in api.calls))

    def test_add_rejects_malformed_created_id_without_followup(self):
        api = StatefulAPI([task("old")], current="old")
        original = api.request
        def malformed_create(method, path, body=None):
            if method == "POST" and path == "/tasks":
                api.calls.append((method, path, body))
                return {"id": "bad\nidentifier"}
            return original(method, path, body)
        api.request = malformed_create
        result = sp.add(api, "Created", True)
        self.assertEqual((result["state"], result["stage"], result["followupMutationApplied"]), ("unknown", "verify", None))
        self.assertFalse(any(call[0] == "POST" and call[1] == "/task-control/current" for call in api.calls))

    @mock.patch.object(sp.time, "sleep")
    def test_auto_next_preserves_orphan_api_order_and_skips_container_parents(self, _sleep):
        now = sp.time.time_ns() // 1_000_000
        values = [
            task("first", dueWithTime=now - 1),
            task("orphan", parentId="missing", dueWithTime=now),
            task("missing-parent-container", subTaskIds=["missing-child"]),
            task("conflicting-container", subTaskIds=["conflict"]),
            task("conflict", parentId="elsewhere", isDone=True),
            task("done-child-container", subTaskIds=["done-child"]),
            task("done-child", parentId="done-child-container", isDone=True),
            task("later", dueWithTime=now),
        ]
        flattened, _ = sp.build_hierarchy(values, include_done=False)
        self.assertEqual(sp._runnable_ids(flattened), ["first", "orphan", "later"])
        api = StatefulAPI(values, current="first")
        result = sp.complete(api, "first", True)
        self.assertEqual((result["autoNext"], result["nextTaskId"]), ("started", "orphan"))

    def test_named_alert_and_notification_cli_parsing(self):
        with mock.patch.object(sp, "alert", return_value=({"ok": True}, 0)) as alert:
            sp.run(["alert", "--urgency", "low", "--silent", "--volume", "50", "--", "Real", "title"])
            alert.assert_called_once_with("Real title", "low", None, True, 50)
        with mock.patch.object(sp, "test_notification", return_value=({"ok": True}, 0)) as notification:
            sp.run(["test-notification", "--urgency", "normal"])
            notification.assert_called_once_with("normal")
        with self.assertRaises(sp.BridgeError):
            sp.run(["alert", "Real title"])
        with self.assertRaises(sp.BridgeError):
            sp.validate_urgency("urgent")

    def test_volume_cli_defaults_and_rejects_invalid_values(self):
        with mock.patch.object(sp, "preview_sound", return_value=({"ok": True}, 0)) as preview:
            sp.run(["preview-sound"])
            preview.assert_called_once_with(None, 100)
            preview.reset_mock()
            sp.run(["preview-sound", "--volume", "0", "--sound", "/tmp/tone.wav"])
            preview.assert_called_once_with("/tmp/tone.wav", 0)
        with mock.patch.object(sp, "alert", return_value=({"ok": True}, 0)) as alert:
            sp.run(["alert", "--urgency", "critical", "--", "Done"])
            alert.assert_called_once_with("Done", "critical", None, False, 100)
        for value in ("-1", "101", "50.0", "nope", ""):
            with self.subTest(value=value), self.assertRaisesRegex(sp.BridgeError, "Volume must be"):
                sp.run(["preview-sound", "--volume", value])
            with self.subTest(value=value), self.assertRaisesRegex(sp.BridgeError, "Volume must be"):
                sp.run(["alert", "--urgency", "normal", "--volume", value, "--", "Done"])

    @mock.patch.object(sp.os, "killpg")
    @mock.patch.object(sp.subprocess, "Popen")
    @mock.patch.object(sp, "resolve_sound", return_value=Path("/tmp/tone.wav"))
    @mock.patch.object(sp, "_player_command", return_value=["player", "/tmp/tone.wav"])
    def test_preview_caps_and_cleans_process_group_without_notification(self, _command, _sound, popen, killpg):
        process = popen.return_value
        process.pid = 4321
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired("player", sp.PREVIEW_PLAYBACK_TIMEOUT),
            subprocess.TimeoutExpired("player", sp.PREVIEW_TERM_GRACE),
            0,
        ]
        result, code = sp.preview_sound()
        self.assertEqual((code, result["sound"]["capped"]), (0, True))
        self.assertEqual(killpg.call_args_list, [mock.call(4321, signal.SIGTERM), mock.call(4321, signal.SIGKILL)])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @mock.patch.object(sp.subprocess, "Popen")
    @mock.patch.object(sp, "resolve_sound", return_value=Path("/tmp/tone.wav"))
    @mock.patch.object(sp, "_player_command", return_value=["player", "/tmp/tone.wav"])
    def test_preview_blocks_term_until_spawn_and_handler_install(self, _command, _sound, popen):
        events = []
        process = popen.return_value
        process.wait.return_value = 0
        popen.side_effect = lambda *args, **kwargs: events.append("spawn") or process
        def mask(how, value):
            events.append("block" if how == signal.SIG_BLOCK else "unblock")
            return {signal.SIGINT}
        def install(_signum, _handler):
            events.append("handler")
        with mock.patch.object(sp.signal, "pthread_sigmask", side_effect=mask), \
             mock.patch.object(sp.signal, "getsignal", return_value=signal.SIG_DFL), \
             mock.patch.object(sp.signal, "signal", side_effect=install):
            result, code = sp.preview_sound()
        self.assertEqual((code, result["sound"]["ok"]), (0, True))
        self.assertEqual(events[:4], ["block", "spawn", "handler", "unblock"])

    @mock.patch.object(sp.os, "killpg")
    @mock.patch.object(sp.subprocess, "Popen")
    @mock.patch.object(sp, "resolve_sound", return_value=Path("/tmp/tone.wav"))
    @mock.patch.object(sp, "_player_command", return_value=["player", "/tmp/tone.wav"])
    def test_preview_cancellation_during_unblock_cleans_child_group(self, _command, _sound, popen, killpg):
        process = popen.return_value
        process.pid = 9876
        process.poll.return_value = None
        process.wait.return_value = 0
        masks = [set(), KeyboardInterrupt(), set()]
        with mock.patch.object(sp.signal, "pthread_sigmask", side_effect=masks) as pthread_sigmask, \
             mock.patch.object(sp.signal, "getsignal", return_value=signal.SIG_DFL), \
             mock.patch.object(sp.signal, "signal"):
            with self.assertRaises(KeyboardInterrupt):
                sp.preview_sound()
        killpg.assert_called_with(9876, signal.SIGTERM)
        self.assertEqual(pthread_sigmask.call_count, 3)


if __name__ == "__main__":
    unittest.main()
