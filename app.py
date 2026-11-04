"""Aplikasi Streamlit untuk sistem pakar Ripple Down Rules (RDR).

Domain: rekomendasi alat musik untuk pemula, dengan pakar = pemilik toko musik.
Jalankan dengan:  streamlit run app.py
"""

import json
import os

import pandas as pd
import streamlit as st

import rdr

KB_FILE = os.environ.get("RDR_KB_PATH", rdr.KB_PATH)
SCENARIO_PATH = os.path.join(rdr.BASE_DIR, "scenario.json")
SCHEMA = rdr.SCHEMA
ATTRS = SCHEMA["attributes"]
OTHER = "➕ Lainnya (isi baru)"

st.set_page_config(page_title="RDR Rekomendasi Alat Musik", page_icon="🎸", layout="wide")


# ---------------------------------------------------------------------------
# Utilitas umum
# ---------------------------------------------------------------------------

@st.cache_data
def load_scenario():
    try:
        with open(SCENARIO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"steps": []}


@st.cache_resource
def init_kb():
    """Muat kb.json sekali per proses server, kalau sudah ada."""
    if os.path.exists(KB_FILE):
        try:
            rdr.load_kb(KB_FILE)
            return f"KB dimuat dari {os.path.basename(KB_FILE)} ({rdr.count_nodes()} rule)."
        except Exception as exc:  # noqa: BLE001 - tampilkan apa pun yang salah
            rdr.reset_kb()
            return f"Gagal memuat {os.path.basename(KB_FILE)}: {exc}. Memakai KB kosong."
    return "KB baru (belum ada kb.json)."


def attr_label(attr):
    spec = ATTRS[attr]
    text = attr.replace("_", " ").capitalize()
    return f"{text} ({spec['unit']})" if spec.get("unit") else text


def fmt_val(attr, value):
    spec = ATTRS.get(attr, {})
    if spec.get("type") == "numeric" and spec.get("unit") == "Rp":
        return f"{int(value):,}".replace(",", ".")
    return rdr.format_value(value)


def num_step(spec):
    return 100000 if spec["max"] >= 1_000_000 else 1


def default_case():
    """Nilai awal form: kasus skenario 1 kalau ada, selain itu batas bawah/opsi pertama."""
    steps = load_scenario().get("steps", [])
    base = steps[0]["case"] if steps else {}
    out = {}
    for attr, spec in ATTRS.items():
        if attr in base:
            out[attr] = base[attr]
        elif spec["type"] == "numeric":
            out[attr] = spec["min"]
        else:
            out[attr] = spec["values"][0]
    return out


def case_summary(case):
    return ", ".join(f"{a} = {fmt_val(a, v)}" for a, v in case.items())


def trace_df(trace):
    rows = [{
        "Node": step["node_id"],
        "Kondisi": step["conditions_str"],
        "Kesimpulan node": step["conclusion"],
        "Terpenuhi": "✓" if step["satisfied"] else "✗",
        "Fired": "★ dipakai" if step["fired"] else "",
    } for step in trace]
    df = pd.DataFrame(rows)

    def highlight(row):
        color = "background-color: #fff3b0" if row["Fired"] else ""
        return [color] * len(row)

    return df.style.apply(highlight, axis=1)


def known_conclusions():
    """Daftar kesimpulan dari schema ditambah kesimpulan baru yang sudah ada di KB."""
    out = list(SCHEMA.get("conclusions", []))
    for node in rdr.get_kb().iter_nodes():
        if node.conclusion not in out:
            out.append(node.conclusion)
    return out


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def init_state():
    kb_note = init_kb()
    st.session_state.setdefault("kb_msg", ("info", kb_note))
    for key, val in {
        "stage": None,          # None | "result" | "agreed" | "expert" | "done"
        "case": None,
        "result": None,
        "last_trace": None,
        "expert_round": 0,
        "hint_no": None,
        "flash": None,
        "confirm_reset": False,
        "scn_no": 1,
    }.items():
        st.session_state.setdefault(key, val)
    for attr, val in default_case().items():
        st.session_state.setdefault(f"in_{attr}", val)


def clear_flow():
    st.session_state.stage = None
    st.session_state.case = None
    st.session_state.result = None
    st.session_state.last_trace = None
    st.session_state.flash = None


# --- callback tombol (jalan sebelum script dirender ulang) -------------------

def cb_load_scenario():
    steps = load_scenario().get("steps", [])
    n = int(st.session_state.scn_no)
    if not 1 <= n <= len(steps):
        return
    case = steps[n - 1]["case"]
    for attr in ATTRS:
        if attr in case:
            st.session_state[f"in_{attr}"] = case[attr]
    clear_flow()
    st.session_state.hint_no = n


def cb_save_kb():
    try:
        rdr.save_kb(KB_FILE)
        st.session_state.kb_msg = ("success", f"KB disimpan ke {os.path.basename(KB_FILE)}.")
    except OSError as exc:
        st.session_state.kb_msg = ("error", f"Gagal menyimpan: {exc}")


def cb_load_kb():
    try:
        rdr.load_kb(KB_FILE)
        clear_flow()
        st.session_state.kb_msg = ("success", f"KB dimuat ({rdr.count_nodes()} rule).")
    except FileNotFoundError:
        st.session_state.kb_msg = ("warning", f"{os.path.basename(KB_FILE)} belum ada. Simpan KB dulu.")
    except (OSError, ValueError, KeyError) as exc:
        st.session_state.kb_msg = ("error", f"Gagal memuat: {exc}")


def cb_ask_reset():
    st.session_state.confirm_reset = True


def cb_cancel_reset():
    st.session_state.confirm_reset = False


def cb_do_reset():
    rdr.reset_kb()
    clear_flow()
    st.session_state.confirm_reset = False
    st.session_state.kb_msg = (
        "success",
        "KB direset ke satu rule default. kb.json baru berubah saat ada rule baru atau tombol Save.")


# ---------------------------------------------------------------------------
# Visualisasi tree
# ---------------------------------------------------------------------------

def _esc(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def build_dot(tree, trace):
    path_nodes, path_edges, fired_id = set(), set(), None
    for i, step in enumerate(trace or []):
        path_nodes.add(step["node_id"])
        if step["fired"]:
            fired_id = step["node_id"]
        if i + 1 < len(trace):
            path_edges.add((step["node_id"], trace[i + 1]["node_id"],
                            "true" if step["satisfied"] else "false"))

    lines = [
        "digraph KB {",
        "  rankdir=TB;",
        '  node [shape=box, style="rounded,filled", fillcolor="#ffffff", '
        'fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=10];',
    ]

    def walk(node):
        nid = node["id"]
        conds = rdr.conditions_to_str(node["conditions"])
        label = _esc(f"{nid}: {conds}") + "\\n→ " + _esc(node["conclusion"])
        attrs = [f'label="{label}"']
        if nid in path_nodes:
            attrs.append('fillcolor="#fff3b0"')
        if nid == fired_id:
            attrs.append('fillcolor="#ffd54f"')
            attrs.append("penwidth=2.5")
        lines.append(f"  n{nid} [{', '.join(attrs)}];")
        for branch, child in (("true", node.get("true_child")), ("false", node.get("false_child"))):
            if not child:
                continue
            color = "#2e7d32" if branch == "true" else "#c62828"
            width = 3 if (nid, child["id"], branch) in path_edges else 1
            lines.append(
                f'  n{nid} -> n{child["id"]} [label="{branch}", color="{color}", '
                f'fontcolor="{color}", penwidth={width}];')
            walk(child)

    walk(tree)
    lines.append("}")
    return "\n".join(lines)


def text_tree(tree):
    out = [f"R: {rdr.conditions_to_str(tree['conditions'])} → {tree['conclusion']}"]

    def walk(node, prefix):
        kids = [(tag, node.get(key)) for tag, key in (("T", "true_child"), ("F", "false_child"))
                if node.get(key)]
        for i, (tag, child) in enumerate(kids):
            last = i == len(kids) - 1
            conds = rdr.conditions_to_str(child["conditions"])
            out.append(f"{prefix}{'└─' if last else '├─'} {tag}: N{child['id']} "
                       f"{conds} → {child['conclusion']}")
            walk(child, prefix + ("    " if last else "│   "))

    walk(tree, "")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Bagian UI
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.header("📚 Knowledge Base")
        st.metric("Jumlah rule", rdr.count_nodes(), help="Termasuk rule default (root).")

        broken = rdr.check_consistency()
        if broken:
            st.error("KB tidak konsisten:")
            for b in broken:
                st.caption(f"Node {b['node_id']}: seharusnya '{b['expected']}', "
                           f"hasilnya '{b['got']}'")
        else:
            st.success("Konsisten: semua cornerstone case masih menghasilkan kesimpulannya.")

        c1, c2 = st.columns(2)
        c1.button("💾 Save", on_click=cb_save_kb, key="btn_save_kb")
        c2.button("📂 Load", on_click=cb_load_kb, key="btn_load_kb")

        if st.session_state.confirm_reset:
            st.warning("Hapus semua rule dan mulai dari KB kosong?")
            d1, d2 = st.columns(2)
            d1.button("Ya, reset", on_click=cb_do_reset, type="primary",
                      key="btn_reset_yes")
            d2.button("Batal", on_click=cb_cancel_reset, key="btn_reset_no")
        else:
            st.button("🗑️ Reset KB", on_click=cb_ask_reset, key="btn_reset")

        kind, text = st.session_state.kb_msg
        getattr(st, kind)(text)
        st.caption("Autosave ke kb.json setiap kali rule baru ditambahkan.")


def render_form():
    steps = load_scenario().get("steps", [])
    if steps:
        c1, c2, _ = st.columns([1, 1.4, 3])
        c1.number_input("Skenario ke-", 1, len(steps), step=1, key="scn_no")
        c2.button("📋 Isi dari skenario", on_click=cb_load_scenario,
                  key="btn_scenario", help="Memuat kasus skenario ke form untuk demo cepat.")
        render_hint(steps)

    cols = st.columns(3)
    for i, (attr, spec) in enumerate(ATTRS.items()):
        with cols[i % 3]:
            if spec["type"] == "numeric":
                st.number_input(attr_label(attr), min_value=spec["min"], max_value=spec["max"],
                                step=num_step(spec), format="%d", key=f"in_{attr}")
            else:
                st.selectbox(attr_label(attr), spec["values"], key=f"in_{attr}")

    st.button("🎯 Minta Rekomendasi", type="primary", key="btn_ask", on_click=cb_ask)


def render_hint(steps):
    n = st.session_state.hint_no
    if not n or not 1 <= n <= len(steps):
        return
    step = steps[n - 1]
    with st.expander(f"Naskah demo skenario {n}", expanded=False):
        exp = step.get("expected_system", {})
        st.write(f"**Sistem diharapkan:** {exp.get('conclusion', '-')}")
        if step.get("expert_agrees"):
            st.write("**Pakar:** Setuju.")
        else:
            conds = ", ".join(rdr.cond_to_str(c) for c in step.get("chosen_conditions", []))
            st.write(f"**Pakar:** Tidak setuju, kesimpulan benar: {step.get('expert_conclusion')}")
            st.write(f"**Kondisi dipilih:** {conds}")
            if step.get("note"):
                st.caption(step["note"])
            new = step.get("expected_new_node")
            if new:
                st.caption(f"Rule baru: N{new['id']}, {new['branch']} child dari node {new['parent_id']}.")


def cb_ask():
    case = {attr: st.session_state[f"in_{attr}"] for attr in ATTRS}
    result = rdr.infer(case)
    st.session_state.case = case
    st.session_state.result = result
    st.session_state.last_trace = result["trace"]
    st.session_state.stage = "result"
    st.session_state.flash = None


def render_result_card(result, title):
    with st.container(border=True):
        st.caption(title)
        st.markdown(f"## 🎸 {result['conclusion']}")
        st.caption(f"Kesimpulan dari node {result['fired_node_id']} "
                   f"(node terakhir yang dievaluasi: {result['last_node_id']}).")
    st.dataframe(trace_df(result["trace"]), hide_index=True)


def render_expert():
    case, result = st.session_state.case, st.session_state.result
    rnd = st.session_state.expert_round
    fired = result["fired_node_id"]

    st.subheader("🧑‍🔧 Koreksi pakar")

    # 1. kesimpulan yang benar
    options = known_conclusions() + [OTHER]
    choice = st.selectbox("Kesimpulan yang benar menurut pakar", options, index=None,
                          placeholder="Pilih kesimpulan...", key=f"x{rnd}_concl")
    conclusion = None
    if choice == OTHER:
        conclusion = st.text_input("Kesimpulan baru", key=f"x{rnd}_concl_new").strip() or None
    elif choice:
        conclusion = choice

    # 2. cornerstone vs kasus baru
    cornerstone = rdr.get_cornerstone(fired)
    st.markdown(f"**Kasus baru vs cornerstone case node {fired}** "
                f"(kesimpulan yang akan dianulir: _{result['conclusion']}_)")
    if cornerstone is None:
        st.info("Node default (root) tidak punya cornerstone case, jadi semua nilai kasus baru "
                "ditawarkan sebagai kondisi.")
    rows, diff_flags = [], []
    for attr in ATTRS:
        new = case.get(attr)
        old = cornerstone.get(attr) if cornerstone else None
        rows.append({"Atribut": attr, "Kasus baru": fmt_val(attr, new),
                     "Cornerstone": "-" if cornerstone is None else fmt_val(attr, old)})
        diff_flags.append(cornerstone is not None and new != old)
    cmp_df = pd.DataFrame(rows)
    cmp_style = cmp_df.style.apply(
        lambda row: ["background-color: #ffe0b2" if diff_flags[row.name] else ""] * len(row), axis=1)
    st.dataframe(cmp_style, hide_index=True)

    # 3. difference list
    st.markdown("**Pilih kondisi** (digabung dengan AND). Kondisi yang ditawarkan benar untuk "
                "kasus baru dan salah untuk cornerstone. Untuk atribut numerik, operator dan "
                "nilai batas boleh diedit (misalnya `<= 1000000` jadi `< 1500000`), selama "
                "validasi tetap lolos.")
    diffs = rdr.get_difference_list(case, result)
    if not diffs:
        st.warning("Tidak ada perbedaan antara kasus baru dan cornerstone case, jadi tidak ada "
                   "kondisi yang bisa ditawarkan.")
    selected = []
    for i, d in enumerate(diffs):
        spec = ATTRS[d["attr"]]
        if spec["type"] == "numeric":
            left, mid, right = st.columns([2, 1, 2])
            checked = left.checkbox(d["attr"], key=f"x{rnd}_chk_{i}")
            op = mid.selectbox(
                f"operator {d['attr']}", rdr.NUMERIC_OPS, index=rdr.NUMERIC_OPS.index(d["op"]),
                key=f"x{rnd}_op_{i}", label_visibility="collapsed")
            value = right.number_input(
                f"nilai {d['attr']}", min_value=spec["min"], max_value=spec["max"],
                value=d["value"], step=num_step(spec), format="%d",
                key=f"x{rnd}_val_{i}", label_visibility="collapsed")
        else:
            checked = st.checkbox(rdr.cond_to_str(d), key=f"x{rnd}_chk_{i}")
            op, value = d["op"], d["value"]
        if checked:
            selected.append({"attr": d["attr"], "op": op, "value": value})

    if selected:
        ok, msg = rdr.validate_conditions(case, selected, result)
        if ok:
            st.caption("✅ Kondisi valid: " + " AND ".join(rdr.cond_to_str(c) for c in selected))
        else:
            st.caption(f"⚠️ {msg}")

    # 4. simpan
    b1, b2, _ = st.columns([1, 1, 4])
    save = b1.button("💾 Simpan rule", type="primary", key="btn_save_rule")
    cancel = b2.button("Batal", key="btn_cancel_rule")

    if cancel:
        st.session_state.stage = "result"
        st.rerun()

    if save:
        if not conclusion:
            st.error("Pilih atau isi kesimpulan yang benar dulu.")
        elif conclusion == result["conclusion"]:
            st.error("Kesimpulan pakar sama dengan kesimpulan sistem. Kalau setuju, pilih Setuju.")
        else:
            ok, msg = rdr.validate_conditions(case, selected, result)
            if not ok:
                st.error(msg)
            else:
                parent_id = result["last_node_id"]
                branch = "true" if result["last_satisfied"] else "false"
                try:
                    new_id = rdr.add_rule(case, selected, conclusion, result)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    try:
                        rdr.save_kb(KB_FILE)
                        saved = "KB tersimpan otomatis."
                    except OSError as exc:
                        saved = f"Autosave gagal: {exc}"
                    new_result = rdr.infer(case)
                    st.session_state.result = new_result
                    st.session_state.last_trace = new_result["trace"]
                    st.session_state.stage = "done"
                    st.session_state.flash = (
                        f"Rule N{new_id} ditambahkan: {' AND '.join(rdr.cond_to_str(c) for c in selected)}"
                        f" → {conclusion}, sebagai {branch} child dari node {parent_id}. {saved}")
                    st.rerun()


def render_consult_tab():
    render_form()
    stage = st.session_state.stage
    if stage is None:
        return

    st.divider()
    st.caption("Kasus: " + case_summary(st.session_state.case))
    result = st.session_state.result

    if stage == "result":
        render_result_card(result, "Rekomendasi sistem")
        b1, b2, _ = st.columns([1, 1.3, 4])
        if b1.button("👍 Setuju", key="btn_agree"):
            st.session_state.stage = "agreed"
            st.rerun()
        if b2.button("👎 Tidak setuju", key="btn_disagree"):
            st.session_state.expert_round += 1
            st.session_state.stage = "expert"
            st.rerun()

    elif stage == "agreed":
        render_result_card(result, "Rekomendasi final (disetujui pakar)")
        st.success("Pakar setuju. KB tidak berubah.")

    elif stage == "expert":
        render_result_card(result, "Rekomendasi sistem (ditolak pakar)")
        render_expert()

    elif stage == "done":
        st.success(st.session_state.flash)
        render_result_card(result, "Setelah rule baru, kasus ini sekarang menghasilkan")


def render_tree_tab():
    tree = rdr.get_tree()
    st.caption("Garis hijau = true (exception), merah = false (alternatif). "
               "Jalur kuning = penelusuran konsultasi terakhir, node paling terang = node yang dipakai.")
    st.graphviz_chart(build_dot(tree, st.session_state.last_trace))
    with st.expander("Tampilan teks"):
        st.code(text_tree(tree), language=None)


def main():
    init_state()
    st.title("🎸 RDR: Rekomendasi Alat Musik untuk Pemula")
    st.caption("Sistem pakar Ripple Down Rules. Pakar = pemilik toko musik, "
               "pengetahuan dibangun bertahap lewat koreksi atas kasus yang salah.")
    render_sidebar()
    tab_consult, tab_tree = st.tabs(["Konsultasi", "Tree KB"])
    with tab_consult:
        render_consult_tab()
    with tab_tree:
        render_tree_tab()


main()
