"""Engine Ripple Down Rules (RDR) untuk rekomendasi alat musik pemula.

Tree RDR biner: setiap node punya kondisi (AND), kesimpulan, cornerstone case,
true_child (exception, dievaluasi jika node terpenuhi) dan false_child
(alternatif, dievaluasi jika node tidak terpenuhi).

Bisa dipakai sebagai class (RDRKnowledgeBase) atau lewat fungsi modul yang
mengikuti kontrak (infer, get_difference_list, validate_conditions, add_rule,
get_tree, get_cornerstone, save_kb, load_kb, reset_kb, check_consistency).
"""

import copy
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.json")
KB_PATH = os.path.join(BASE_DIR, "kb.json")

NUMERIC_OPS = ("<", "<=", ">", ">=", "=")
CATEGORICAL_OPS = ("=", "!=")


def load_schema(path=SCHEMA_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SCHEMA = load_schema()


# ---------------------------------------------------------------------------
# A2. Evaluasi kondisi
# ---------------------------------------------------------------------------

def attr_type(attr, schema=None):
    schema = schema or SCHEMA
    if attr not in schema["attributes"]:
        raise ValueError(f"Atribut tidak dikenal: {attr}")
    return schema["attributes"][attr]["type"]


def eval_condition(case, cond, schema=None):
    """True jika kondisi {attr, op, value} berlaku untuk kasus."""
    attr, op, value = cond["attr"], cond["op"], cond["value"]
    numeric = attr_type(attr, schema) == "numeric"
    allowed = NUMERIC_OPS if numeric else CATEGORICAL_OPS
    if op not in allowed:
        raise ValueError(f"Operator '{op}' tidak valid untuk atribut {attr}")
    if attr not in case:
        return False
    actual = case[attr]

    if numeric:
        actual, value = float(actual), float(value)
        if op == "<":
            return actual < value
        if op == "<=":
            return actual <= value
        if op == ">":
            return actual > value
        if op == ">=":
            return actual >= value
        return actual == value

    if op == "=":
        return actual == value
    return actual != value


def node_satisfied(case, node, schema=None):
    """Semua kondisi node benar; list kosong (root) selalu benar."""
    return all(eval_condition(case, c, schema) for c in node.conditions)


def format_value(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def cond_to_str(cond):
    return f"{cond['attr']} {cond['op']} {format_value(cond['value'])}"


def conditions_to_str(conditions):
    if not conditions:
        return "t"
    return " AND ".join(cond_to_str(c) for c in conditions)


# ---------------------------------------------------------------------------
# A1. Struktur node dan KB
# ---------------------------------------------------------------------------

class Node:
    def __init__(self, id, conditions, conclusion, cornerstone_case=None,
                 true_child=None, false_child=None):
        self.id = id
        self.conditions = conditions
        self.conclusion = conclusion
        self.cornerstone_case = cornerstone_case
        self.true_child = true_child
        self.false_child = false_child

    # A6. Serialisasi rekursif
    def to_dict(self):
        return {
            "id": self.id,
            "conditions": copy.deepcopy(self.conditions),
            "conclusion": self.conclusion,
            "cornerstone_case": copy.deepcopy(self.cornerstone_case),
            "true_child": self.true_child.to_dict() if self.true_child else None,
            "false_child": self.false_child.to_dict() if self.false_child else None,
        }

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return None
        return cls(
            id=d["id"],
            conditions=copy.deepcopy(d.get("conditions", [])),
            conclusion=d["conclusion"],
            cornerstone_case=copy.deepcopy(d.get("cornerstone_case")),
            true_child=cls.from_dict(d.get("true_child")),
            false_child=cls.from_dict(d.get("false_child")),
        )

    def __repr__(self):
        return f"Node({self.id}: {conditions_to_str(self.conditions)} -> {self.conclusion})"


class RDRKnowledgeBase:
    def __init__(self, schema=None):
        self.schema = schema or SCHEMA
        self.reset_kb()

    def reset_kb(self):
        self.root = Node(0, [], self.schema["default_conclusion"], None)
        self.next_id = 1

    # --- utilitas tree ---------------------------------------------------

    def iter_nodes(self):
        """Semua node, urut pre-order (node, true, false)."""
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            if node.false_child:
                stack.append(node.false_child)
            if node.true_child:
                stack.append(node.true_child)

    def count_nodes(self):
        return sum(1 for _ in self.iter_nodes())

    def get_node(self, node_id):
        for node in self.iter_nodes():
            if node.id == node_id:
                return node
        raise KeyError(f"Node {node_id} tidak ada")

    def get_parent(self, node_id):
        """(id parent, 'true'/'false'), atau (None, None) untuk root."""
        for node in self.iter_nodes():
            if node.true_child and node.true_child.id == node_id:
                return node.id, "true"
            if node.false_child and node.false_child.id == node_id:
                return node.id, "false"
        return None, None

    def get_tree(self):
        return self.root.to_dict()

    def get_cornerstone(self, node_id):
        return copy.deepcopy(self.get_node(node_id).cornerstone_case)

    # --- A3. Inferensi ---------------------------------------------------

    def infer(self, case):
        conclusion = None
        fired = None
        last = None
        last_satisfied = False
        trace = []

        node = self.root
        while node is not None:
            satisfied = node_satisfied(case, node, self.schema)
            trace.append({
                "node_id": node.id,
                "conditions": copy.deepcopy(node.conditions),
                "conditions_str": conditions_to_str(node.conditions),
                "conclusion": node.conclusion,
                "satisfied": satisfied,
                "fired": False,
            })
            last, last_satisfied = node, satisfied
            if satisfied:
                conclusion, fired = node.conclusion, node
                node = node.true_child
            else:
                node = node.false_child

        for step in trace:
            step["fired"] = step["node_id"] == fired.id

        return {
            "conclusion": conclusion,
            "fired_node_id": fired.id,
            "last_node_id": last.id,
            "last_satisfied": last_satisfied,
            "trace": trace,
        }

    # --- A4. Difference list ---------------------------------------------

    def get_difference_list(self, case, result):
        cornerstone = self.get_node(result["fired_node_id"]).cornerstone_case
        diffs = []
        for attr, spec in self.schema["attributes"].items():
            if attr not in case:
                continue
            new = case[attr]

            if cornerstone is None:
                if spec["type"] == "numeric":
                    diffs.append({"attr": attr, "op": "<=", "value": new})
                    diffs.append({"attr": attr, "op": ">=", "value": new})
                else:
                    diffs.append({"attr": attr, "op": "=", "value": new})
                continue

            if attr not in cornerstone:
                continue
            old = cornerstone[attr]
            if spec["type"] == "numeric":
                if new > old:
                    diffs.append({"attr": attr, "op": ">", "value": old})
                    diffs.append({"attr": attr, "op": ">=", "value": new})
                elif new < old:
                    diffs.append({"attr": attr, "op": "<", "value": old})
                    diffs.append({"attr": attr, "op": "<=", "value": new})
            elif new != old:
                diffs.append({"attr": attr, "op": "=", "value": new})
                diffs.append({"attr": attr, "op": "!=", "value": old})
        return diffs

    # --- A5. Validasi dan tambah rule ------------------------------------

    def validate_conditions(self, case, conditions, result):
        if not conditions:
            return False, "Pilih minimal satu kondisi."

        for cond in conditions:
            attr, op = cond.get("attr"), cond.get("op")
            if attr not in self.schema["attributes"]:
                return False, f"Atribut tidak dikenal: {attr}"
            allowed = NUMERIC_OPS if attr_type(attr, self.schema) == "numeric" else CATEGORICAL_OPS
            if op not in allowed:
                return False, f"Operator '{op}' tidak valid untuk atribut {attr}."
            if attr_type(attr, self.schema) == "numeric":
                try:
                    float(cond.get("value"))
                except (TypeError, ValueError):
                    return False, f"Nilai {attr} harus berupa angka."
            if not eval_condition(case, cond, self.schema):
                return False, f"Kondisi '{cond_to_str(cond)}' tidak berlaku untuk kasus baru."

        cornerstone = self.get_node(result["fired_node_id"]).cornerstone_case
        if cornerstone is not None and all(
                eval_condition(cornerstone, c, self.schema) for c in conditions):
            return False, (
                f"Kondisi juga berlaku untuk cornerstone case node {result['fired_node_id']}; "
                "tambahkan atau ubah kondisi agar kasus itu tidak ikut berubah."
            )
        return True, ""

    def add_rule(self, case, conditions, conclusion, result):
        if not conclusion:
            raise ValueError("Kesimpulan tidak boleh kosong.")
        ok, msg = self.validate_conditions(case, conditions, result)
        if not ok:
            raise ValueError(msg)

        parent = self.get_node(result["last_node_id"])
        branch = "true_child" if result["last_satisfied"] else "false_child"
        if getattr(parent, branch) is not None:
            raise ValueError(
                f"Hasil inferensi sudah usang: node {parent.id} sudah punya {branch}. "
                "Jalankan infer ulang."
            )

        node = Node(self.next_id, copy.deepcopy(conditions), conclusion, copy.deepcopy(case))
        setattr(parent, branch, node)
        self.next_id += 1

        broken = self.check_consistency()
        if broken:
            setattr(parent, branch, None)
            self.next_id -= 1
            raise ValueError(f"Rule baru merusak konsistensi KB: {broken}")
        return node.id

    def check_consistency(self):
        """Node yang cornerstone case-nya tidak lagi menghasilkan kesimpulan node itu."""
        broken = []
        for node in self.iter_nodes():
            if node.cornerstone_case is None:
                continue
            got = self.infer(node.cornerstone_case)["conclusion"]
            if got != node.conclusion:
                broken.append({"node_id": node.id, "expected": node.conclusion, "got": got})
        return broken

    # --- A6. Persistensi -------------------------------------------------

    def to_dict(self):
        return {"next_id": self.next_id, "root": self.root.to_dict()}

    def from_dict(self, d):
        self.root = Node.from_dict(d["root"])
        self.next_id = d.get("next_id") or max(n.id for n in self.iter_nodes()) + 1

    def save_kb(self, path=KB_PATH):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load_kb(self, path=KB_PATH):
        with open(path, encoding="utf-8") as f:
            self.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Fungsi modul sesuai kontrak (dipakai app.py), memakai satu KB global.
# ---------------------------------------------------------------------------

_kb = RDRKnowledgeBase()


def get_kb():
    return _kb


def infer(case):
    return _kb.infer(case)


def get_difference_list(case, result):
    return _kb.get_difference_list(case, result)


def validate_conditions(case, conditions, result):
    return _kb.validate_conditions(case, conditions, result)


def add_rule(case, conditions, conclusion, result):
    return _kb.add_rule(case, conditions, conclusion, result)


def get_tree():
    return _kb.get_tree()


def get_cornerstone(node_id):
    return _kb.get_cornerstone(node_id)


def save_kb(path=KB_PATH):
    _kb.save_kb(path)


def load_kb(path=KB_PATH):
    _kb.load_kb(path)


def reset_kb():
    _kb.reset_kb()


def check_consistency():
    return _kb.check_consistency()


def count_nodes():
    return _kb.count_nodes()
