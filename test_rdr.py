"""Tes engine RDR. Jalankan: python -m unittest -v test_rdr  (atau pytest)."""

import json
import os
import tempfile
import unittest

import rdr
from rdr import (Node, RDRKnowledgeBase, cond_to_str, conditions_to_str,
                 eval_condition, node_satisfied)

with open(os.path.join(rdr.BASE_DIR, "scenario.json"), encoding="utf-8") as f:
    SCENARIO = json.load(f)
STEPS = SCENARIO["steps"]


def strip_cornerstones(tree):
    if tree is None:
        return None
    return {
        "id": tree["id"],
        "conditions": tree["conditions"],
        "conclusion": tree["conclusion"],
        "true_child": strip_cornerstones(tree["true_child"]),
        "false_child": strip_cornerstones(tree["false_child"]),
    }


def build_scenario_kb():
    kb = RDRKnowledgeBase()
    for step in STEPS:
        if not step["expert_agrees"]:
            result = kb.infer(step["case"])
            kb.add_rule(step["case"], step["chosen_conditions"], step["expert_conclusion"], result)
    return kb


class TestA1Structure(unittest.TestCase):
    def test_new_kb_has_single_root(self):
        kb = RDRKnowledgeBase()
        self.assertEqual(kb.count_nodes(), 1)
        self.assertEqual(kb.root.id, 0)
        self.assertEqual(kb.root.conditions, [])
        self.assertEqual(kb.root.conclusion, rdr.SCHEMA["default_conclusion"])
        self.assertIsNone(kb.root.cornerstone_case)
        self.assertIsNone(kb.root.true_child)
        self.assertIsNone(kb.root.false_child)
        self.assertEqual(kb.next_id, 1)


class TestA2Conditions(unittest.TestCase):
    case = {"budget": 2000000, "genre": "rock"}

    def check(self, attr, op, value, expected):
        self.assertEqual(eval_condition(self.case, {"attr": attr, "op": op, "value": value}), expected)

    def test_numeric_operators(self):
        self.check("budget", "<", 2000001, True)
        self.check("budget", "<", 2000000, False)
        self.check("budget", "<=", 2000000, True)
        self.check("budget", "<=", 1999999, False)
        self.check("budget", ">", 1999999, True)
        self.check("budget", ">", 2000000, False)
        self.check("budget", ">=", 2000000, True)
        self.check("budget", ">=", 2000001, False)
        self.check("budget", "=", 2000000, True)
        self.check("budget", "=", 2000000.0, True)
        self.check("budget", "=", 1, False)

    def test_categorical_operators(self):
        self.check("genre", "=", "rock", True)
        self.check("genre", "=", "pop", False)
        self.check("genre", "!=", "pop", True)
        self.check("genre", "!=", "rock", False)

    def test_invalid_operator_raises(self):
        with self.assertRaises(ValueError):
            eval_condition(self.case, {"attr": "genre", "op": "<", "value": "rock"})
        with self.assertRaises(ValueError):
            eval_condition(self.case, {"attr": "budget", "op": "!=", "value": 1})
        with self.assertRaises(ValueError):
            eval_condition(self.case, {"attr": "warna", "op": "=", "value": "merah"})

    def test_missing_attribute_is_false(self):
        self.check("umur", "<=", 12, False)

    def test_node_satisfied(self):
        self.assertTrue(node_satisfied(self.case, Node(0, [], "x")))
        both = [{"attr": "genre", "op": "=", "value": "rock"},
                {"attr": "budget", "op": "<=", "value": 2000000}]
        self.assertTrue(node_satisfied(self.case, Node(1, both, "x")))
        both[1]["value"] = 1000000
        self.assertFalse(node_satisfied(self.case, Node(1, both, "x")))

    def test_cond_to_str(self):
        self.assertEqual(cond_to_str({"attr": "budget", "op": "<=", "value": 1500000}), "budget <= 1500000")
        self.assertEqual(cond_to_str({"attr": "budget", "op": "<=", "value": 1500000.0}), "budget <= 1500000")
        self.assertEqual(cond_to_str({"attr": "genre", "op": "!=", "value": "pop"}), "genre != pop")
        self.assertEqual(conditions_to_str([]), "t")


class TestA3Inference(unittest.TestCase):
    def test_initial_kb_always_default(self):
        kb = RDRKnowledgeBase()
        for step in STEPS:
            result = kb.infer(step["case"])
            self.assertEqual(result["conclusion"], "Gitar akustik")
            self.assertEqual(result["fired_node_id"], 0)
            self.assertEqual(result["last_node_id"], 0)
            self.assertTrue(result["last_satisfied"])
            self.assertEqual(len(result["trace"]), 1)
            self.assertTrue(result["trace"][0]["fired"])

    def test_trace_records_every_evaluated_node(self):
        kb = build_scenario_kb()
        # Kasus 11: R -> N1 (x) -> N4 (x) -> N6 (x) -> N7 (x) -> N9 (v)
        result = kb.infer(STEPS[10]["case"])
        self.assertEqual([t["node_id"] for t in result["trace"]], [0, 1, 4, 6, 7, 9])
        self.assertEqual([t["satisfied"] for t in result["trace"]], [True, False, False, False, False, True])
        self.assertEqual([t["node_id"] for t in result["trace"] if t["fired"]], [9])
        self.assertEqual(result["conclusion"], "Ukulele")


class TestA4DifferenceList(unittest.TestCase):
    def test_root_offers(self):
        kb = RDRKnowledgeBase()
        case = STEPS[1]["case"]
        diffs = kb.get_difference_list(case, kb.infer(case))
        for attr, spec in rdr.SCHEMA["attributes"].items():
            if spec["type"] == "numeric":
                self.assertIn({"attr": attr, "op": "<=", "value": case[attr]}, diffs)
                self.assertIn({"attr": attr, "op": ">=", "value": case[attr]}, diffs)
            else:
                self.assertIn({"attr": attr, "op": "=", "value": case[attr]}, diffs)
        self.assertEqual(len(diffs), 3 * 2 + 4)

    def test_offers_against_cornerstone(self):
        kb = build_scenario_kb()
        # Kasus 12 menembak N2 (cornerstone = kasus 3, budget 5jt)
        case = {**STEPS[11]["case"], "budget": 1200000, "umur": 30}
        result = kb.infer({**case, "budget": 2000000})
        diffs = kb.get_difference_list(case, result)
        self.assertIn({"attr": "budget", "op": "<", "value": 5000000}, diffs)
        self.assertIn({"attr": "budget", "op": "<=", "value": 1200000}, diffs)
        self.assertIn({"attr": "umur", "op": ">", "value": 20}, diffs)
        self.assertIn({"attr": "umur", "op": ">=", "value": 30}, diffs)

    def test_categorical_offers(self):
        kb = build_scenario_kb()
        case = {**STEPS[3]["case"], "budget": 5000000}  # rock, rumah -> fired N1 (cs: kasus 2)
        case["nyanyi_sambil_main"] = "ya"
        result = kb.infer(case)
        self.assertEqual(result["fired_node_id"], 1)
        diffs = kb.get_difference_list(case, result)
        self.assertIn({"attr": "nyanyi_sambil_main", "op": "=", "value": "ya"}, diffs)
        self.assertIn({"attr": "nyanyi_sambil_main", "op": "!=", "value": "tidak"}, diffs)

    def test_offers_true_for_case_false_for_cornerstone(self):
        kb = RDRKnowledgeBase()
        for step in STEPS:
            case = step["case"]
            result = kb.infer(case)
            cornerstone = kb.get_cornerstone(result["fired_node_id"])
            diffs = kb.get_difference_list(case, result)
            for cond in diffs:
                self.assertTrue(eval_condition(case, cond), f"kasus {step['no']}: {cond}")
                if cornerstone is not None:
                    self.assertFalse(eval_condition(cornerstone, cond), f"kasus {step['no']}: {cond}")
            if not step["expert_agrees"]:
                kb.add_rule(case, step["chosen_conditions"], step["expert_conclusion"], result)

    def test_identical_case_has_no_difference(self):
        kb = build_scenario_kb()
        case = STEPS[2]["case"]  # cornerstone N2
        self.assertEqual(kb.get_difference_list(case, kb.infer(case)), [])


class TestA5ValidateAndAdd(unittest.TestCase):
    def setUp(self):
        self.kb = RDRKnowledgeBase()
        self.kb.add_rule(STEPS[1]["case"], STEPS[1]["chosen_conditions"],
                         STEPS[1]["expert_conclusion"], self.kb.infer(STEPS[1]["case"]))
        self.case = STEPS[2]["case"]
        self.result = self.kb.infer(self.case)  # fired N1, cornerstone kasus 2

    def test_empty_conditions_rejected(self):
        ok, msg = self.kb.validate_conditions(self.case, [], self.result)
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_condition_false_for_new_case_rejected(self):
        ok, _ = self.kb.validate_conditions(
            self.case, [{"attr": "tempat_tinggal", "op": "=", "value": "rumah"}], self.result)
        self.assertFalse(ok)

    def test_condition_true_for_cornerstone_rejected(self):
        ok, msg = self.kb.validate_conditions(
            self.case, [{"attr": "genre", "op": "=", "value": "rock"}], self.result)
        self.assertFalse(ok)
        self.assertIn("cornerstone", msg)

    def test_conjunction_only_needs_to_exclude_cornerstone(self):
        conds = [{"attr": "genre", "op": "=", "value": "rock"},
                 {"attr": "tempat_tinggal", "op": "=", "value": "kos"}]
        ok, _ = self.kb.validate_conditions(self.case, conds, self.result)
        self.assertTrue(ok)

    def test_invalid_operator_or_value_rejected(self):
        ok, _ = self.kb.validate_conditions(
            self.case, [{"attr": "genre", "op": ">", "value": "rock"}], self.result)
        self.assertFalse(ok)
        ok, _ = self.kb.validate_conditions(
            self.case, [{"attr": "budget", "op": "<=", "value": "banyak"}], self.result)
        self.assertFalse(ok)

    def test_edited_threshold(self):
        # Cornerstone budget 5jt, kasus baru budget 5jt juga: budget <= 6jt tetap kena cornerstone
        case = {**self.case, "budget": 3000000}
        result = self.kb.infer(case)
        ok, _ = self.kb.validate_conditions(case, [{"attr": "budget", "op": "<=", "value": 4000000}], result)
        self.assertTrue(ok)
        ok, _ = self.kb.validate_conditions(case, [{"attr": "budget", "op": "<=", "value": 6000000}], result)
        self.assertFalse(ok)

    def test_add_rule_gives_expert_conclusion(self):
        new_id = self.kb.add_rule(self.case, STEPS[2]["chosen_conditions"],
                                  STEPS[2]["expert_conclusion"], self.result)
        self.assertEqual(new_id, 2)
        result = self.kb.infer(self.case)
        self.assertEqual(result["conclusion"], STEPS[2]["expert_conclusion"])
        self.assertEqual(result["fired_node_id"], new_id)
        self.assertEqual(self.kb.get_cornerstone(new_id), self.case)
        self.assertEqual(self.kb.get_parent(new_id), (1, "true"))

    def test_add_rule_rejects_invalid_conditions(self):
        with self.assertRaises(ValueError):
            self.kb.add_rule(self.case, [], "Ukulele", self.result)
        self.assertEqual(self.kb.count_nodes(), 2)

    def test_add_rule_rejects_stale_result(self):
        self.kb.add_rule(self.case, STEPS[2]["chosen_conditions"], STEPS[2]["expert_conclusion"], self.result)
        with self.assertRaises(ValueError):
            self.kb.add_rule(self.case, [{"attr": "umur", "op": "<=", "value": 20}], "Ukulele", self.result)

    def test_cornerstone_is_a_copy(self):
        case = dict(self.case)
        new_id = self.kb.add_rule(case, STEPS[2]["chosen_conditions"], STEPS[2]["expert_conclusion"], self.result)
        case["genre"] = "pop"
        self.assertEqual(self.kb.get_cornerstone(new_id)["genre"], "rock")


class TestA6Persistence(unittest.TestCase):
    def test_save_load_identical_inference(self):
        kb = build_scenario_kb()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kb.json")
            kb.save_kb(path)
            loaded = RDRKnowledgeBase()
            loaded.load_kb(path)
        self.assertEqual(loaded.get_tree(), kb.get_tree())
        self.assertEqual(loaded.next_id, kb.next_id)
        for step in STEPS:
            self.assertEqual(loaded.infer(step["case"]), kb.infer(step["case"]))

    def test_from_dict_without_next_id(self):
        kb = build_scenario_kb()
        loaded = RDRKnowledgeBase()
        loaded.from_dict({"root": kb.get_tree()})
        self.assertEqual(loaded.next_id, 11)

    def test_reset(self):
        kb = build_scenario_kb()
        kb.reset_kb()
        self.assertEqual(kb.count_nodes(), 1)
        self.assertEqual(kb.next_id, 1)

    def test_module_level_api(self):
        rdr.reset_kb()
        try:
            for step in STEPS:
                result = rdr.infer(step["case"])
                if not step["expert_agrees"]:
                    rdr.add_rule(step["case"], step["chosen_conditions"], step["expert_conclusion"], result)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "kb.json")
                rdr.save_kb(path)
                rdr.reset_kb()
                self.assertEqual(rdr.count_nodes(), 1)
                rdr.load_kb(path)
            self.assertEqual(strip_cornerstones(rdr.get_tree()), SCENARIO["expected_final_tree"])
            self.assertEqual(rdr.check_consistency(), [])
        finally:
            rdr.reset_kb()


class TestA7Scenario(unittest.TestCase):
    def test_full_scenario(self):
        kb = RDRKnowledgeBase()
        for step in STEPS:
            with self.subTest(kasus=step["no"]):
                case = step["case"]
                result = kb.infer(case)
                for key, value in step["expected_system"].items():
                    self.assertEqual(result[key], value, f"kasus {step['no']}: {key}")

                if step["expert_agrees"]:
                    continue

                diffs = kb.get_difference_list(case, result)
                for cond in step["chosen_conditions"]:
                    if "note" in step:  # threshold diedit: atributnya harus tetap ditawarkan
                        self.assertIn(cond["attr"], [d["attr"] for d in diffs])
                    else:
                        self.assertIn(cond, diffs)

                ok, msg = kb.validate_conditions(case, step["chosen_conditions"], result)
                self.assertTrue(ok, msg)

                new_id = kb.add_rule(case, step["chosen_conditions"], step["expert_conclusion"], result)
                expected = step["expected_new_node"]
                self.assertEqual(new_id, expected["id"])
                self.assertEqual(kb.get_parent(new_id), (expected["parent_id"], expected["branch"]))
                self.assertEqual(kb.infer(case)["conclusion"], step["expert_conclusion"])
                self.assertEqual(kb.check_consistency(), [])

        self.assertEqual(strip_cornerstones(kb.get_tree()), SCENARIO["expected_final_tree"])
        self.assertEqual(kb.count_nodes(), 11)

    def test_final_kb_reproduces_all_expert_answers(self):
        kb = build_scenario_kb()
        for step in STEPS:
            expected = step["expected_system"]["conclusion"] if step["expert_agrees"] else step["expert_conclusion"]
            self.assertEqual(kb.infer(step["case"])["conclusion"], expected, f"kasus {step['no']}")


if __name__ == "__main__":
    unittest.main()
