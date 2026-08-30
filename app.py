import io
import json
import re
import uuid
import zipfile
from copy import deepcopy

import pandas as pd
import pymupdf
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

st.set_page_config(page_title="Law Review PDF Workspace", page_icon="📚", layout="wide")

# ---------------- State ----------------
def init_state():
    defaults = {
        "sources": [],
        "selected": None,
        "history": [],
        "future": [],
        "project_name": "Untitled Law Review Article",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def snapshot():
    return deepcopy(st.session_state.sources)


def checkpoint():
    st.session_state.history.append(snapshot())
    st.session_state.history = st.session_state.history[-30:]
    st.session_state.future = []


def undo():
    if st.session_state.history:
        st.session_state.future.append(snapshot())
        st.session_state.sources = st.session_state.history.pop()
        valid = {s["id"] for s in st.session_state.sources}
        if st.session_state.selected not in valid:
            st.session_state.selected = st.session_state.sources[0]["id"] if st.session_state.sources else None


def redo():
    if st.session_state.future:
        st.session_state.history.append(snapshot())
        st.session_state.sources = st.session_state.future.pop()


def new_id():
    return "SRC-" + uuid.uuid4().hex[:8].upper()


def get_source(source_id):
    return next(s for s in st.session_state.sources if s["id"] == source_id)


def page_count(pdf_bytes):
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return len(doc)


def add_uploads(files):
    existing = {(s["filename"], len(s["pdf"])) for s in st.session_state.sources}
    additions = []
    for f in files:
        b = f.getvalue()
        marker = (f.name, len(b))
        if marker not in existing:
            try:
                pages = page_count(b)
            except Exception:
                st.error(f"Could not open {f.name} as a PDF.")
                continue
            additions.append({
                "id": new_id(), "filename": f.name, "title": f.name.rsplit(".", 1)[0],
                "pdf": b, "footnote": 1, "pages": pages, "annotations": {},
                "label_position": [0.76, 0.02, 0.22, 0.06],
            })
            existing.add(marker)
    if additions:
        checkpoint()
        st.session_state.sources.extend(additions)
        st.session_state.selected = additions[0]["id"]


# ---------------- Labels / ordering ----------------
def calculated_rows():
    counts = {}
    for s in st.session_state.sources:
        counts[s["footnote"]] = counts.get(s["footnote"], 0) + 1
    seen = {}
    rows = []
    for order, s in enumerate(st.session_state.sources, 1):
        fn = s["footnote"]
        seen[fn] = seen.get(fn, 0) + 1
        label = str(fn) if counts[fn] == 1 else f"{fn}.{seen[fn]}"
        rows.append((s, label, order))
    return rows


def label_map():
    return {s["id"]: label for s, label, _ in calculated_rows()}


def move_source(source_id, delta):
    idx = next(i for i, s in enumerate(st.session_state.sources) if s["id"] == source_id)
    new_idx = max(0, min(len(st.session_state.sources) - 1, idx + delta))
    if new_idx != idx:
        checkpoint()
        item = st.session_state.sources.pop(idx)
        st.session_state.sources.insert(new_idx, item)


# ---------------- Canvas conversion ----------------
def render_page(pdf_bytes, page_index, max_width=900):
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_index]
        zoom = min(max_width / page.rect.width, 2.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        return image, page.rect.width, page.rect.height


def ann_to_fabric(ann, width, height):
    kind = ann["kind"]
    obj = {
        "type": "rect", "left": ann["x"] * width, "top": ann["y"] * height,
        "width": ann["w"] * width, "height": ann["h"] * height,
        "scaleX": 1, "scaleY": 1, "angle": 0,
        "strokeWidth": 3 if kind == "box" else 1,
        "selectable": True,
    }
    if kind == "box":
        obj.update(stroke="#ff0000", fill="rgba(255,0,0,0)")
    elif kind == "highlight":
        obj.update(stroke="#e0b000", fill="rgba(255,235,0,0.35)")
    else:
        obj.update(stroke="#8b1e3f", fill="rgba(255,245,248,0.45)")
    return obj


def infer_kind(obj):
    stroke = str(obj.get("stroke", "")).lower()
    fill = str(obj.get("fill", "")).lower()
    if "255,235,0" in fill or stroke == "#e0b000":
        return "highlight"
    if "255,245,248" in fill or stroke == "#8b1e3f":
        return "note"
    return "box"


def canvas_to_annotations(objects, width, height, existing_notes, note_text):
    result = []
    note_i = 0
    for obj in objects or []:
        if obj.get("type") != "rect":
            continue
        kind = infer_kind(obj)
        w = float(obj.get("width", 0)) * float(obj.get("scaleX", 1))
        h = float(obj.get("height", 0)) * float(obj.get("scaleY", 1))
        x = float(obj.get("left", 0))
        y = float(obj.get("top", 0))
        text = ""
        if kind == "note":
            text = existing_notes[note_i] if note_i < len(existing_notes) else note_text.strip()
            note_i += 1
        result.append({
            "kind": kind,
            "x": max(0, min(1, x / width)), "y": max(0, min(1, y / height)),
            "w": max(0.002, min(1, w / width)), "h": max(0.002, min(1, h / height)),
            "text": text,
        })
    return result


# ---------------- PDF export ----------------
def pdf_rect(page, ann):
    return pymupdf.Rect(
        ann["x"] * page.rect.width, ann["y"] * page.rect.height,
        (ann["x"] + ann["w"]) * page.rect.width,
        (ann["y"] + ann["h"]) * page.rect.height,
    )


def annotate_source(source, label):
    doc = pymupdf.open(stream=source["pdf"], filetype="pdf")

    # Add saved annotations to each applicable page.
    for page_no, anns in source["annotations"].items():
        page = doc[int(page_no)]

        for ann in anns:
            rect = pdf_rect(page, ann)

            # Transparent rectangle with a red border.
            if ann["kind"] == "box":
                a = page.add_rect_annot(rect)
                a.set_colors(stroke=(1, 0, 0))
                a.set_border(width=2)
                a.set_info(subject="Law Review proposition box")
                a.update(opacity=1)

            # Translucent yellow region highlight.
            elif ann["kind"] == "highlight":
                a = page.add_rect_annot(rect)
                a.set_colors(
                    stroke=(0.88, 0.69, 0),
                    fill=(1, 0.92, 0),
                )
                a.set_border(width=0.5)
                a.set_info(subject="Law Review region highlight")
                a.update(opacity=0.35)

            # Editable free-form note.
            elif ann["kind"] == "note":
                a = page.add_freetext_annot(
                    rect,
                    ann.get("text") or "Note",
                    fontsize=9,
                    text_color=(0.55, 0.12, 0.25),
                    fill_color=(1, 0.96, 0.97),
                    align=pymupdf.TEXT_ALIGN_LEFT,
                )

                # Set the border after creating the annotation.
                a.set_border(width=1)
                a.set_colors(
                    stroke=(0.55, 0.12, 0.25),
                    fill=(1, 0.96, 0.97),
                )
                a.set_info(subject="Law Review editor note")
                a.update(opacity=0.95)

    # Add the calculated footnote label to page 1 only.
    page = doc[0]
    x, y, w, h = source["label_position"]

    rect = pymupdf.Rect(
        x * page.rect.width,
        y * page.rect.height,
        (x + w) * page.rect.width,
        (y + h) * page.rect.height,
    )

    text = f"FN {label}\n{source['id']}"

    a = page.add_freetext_annot(
        rect,
        text,
        fontsize=9,
        text_color=(0.05, 0.12, 0.35),
        fill_color=(1, 1, 1),
        align=pymupdf.TEXT_ALIGN_CENTER,
    )

    # Set the label border after creating the annotation.
    a.set_border(width=1)
    a.set_colors(
        stroke=(0.05, 0.12, 0.35),
        fill=(1, 1, 1),
    )
    a.set_info(subject="Calculated footnote label")
    a.update(opacity=1)

    output = doc.tobytes(
        garbage=4,
        deflate=True,
  


def build_exports():
    labels = label_map()
    separate = []
    merged = pymupdf.open()
    manifest_rows = []
    current_page = 1
    for source in st.session_state.sources:
        data = annotate_source(source, labels[source["id"]])
        separate.append((f"FN_{labels[source['id']].replace('.', '_')}_{source['id']}.pdf", data))
        part = pymupdf.open(stream=data, filetype="pdf")
        start = current_page
        merged.insert_pdf(part)
        current_page += len(part)
        manifest_rows.append({
            "source_id": source["id"], "display_label": labels[source["id"]],
            "footnote": source["footnote"], "title": source["title"],
            "original_filename": source["filename"], "start_page": start,
            "end_page": current_page - 1, "annotation_count": sum(len(v) for v in source["annotations"].values()),
        })
        part.close()
    consolidated = merged.tobytes(garbage=4, deflate=True)
    merged.close()
    manifest = {"project": st.session_state.project_name, "sources": manifest_rows}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("consolidated.pdf", consolidated)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("manifest.csv", pd.DataFrame(manifest_rows).to_csv(index=False))
        for name, data in separate:
            z.writestr(f"sources/{name}", data)
    return out.getvalue(), consolidated


# ---------------- UI ----------------
init_state()
st.title("📚 Law Review PDF Workspace")
st.caption("Prototype: organize sources by footnote, draw editable annotations, and export a consolidated PDF.")

with st.sidebar:
    st.header("Project")
    st.session_state.project_name = st.text_input("Article name", st.session_state.project_name)
    uploads = st.file_uploader("Add source PDFs", type="pdf", accept_multiple_files=True)
    if uploads:
        add_uploads(uploads)
    u1, u2 = st.columns(2)
    u1.button("↶ Undo", on_click=undo, disabled=not st.session_state.history, use_container_width=True)
    u2.button("↷ Redo", on_click=redo, disabled=not st.session_state.future, use_container_width=True)

    st.header("Source order")
    labels = label_map()
    for i, source in enumerate(st.session_state.sources):
        marker = "●" if source["id"] == st.session_state.selected else "○"
        if st.button(f"{marker} FN {labels[source['id']]} · {source['title']}", key=f"select_{source['id']}", use_container_width=True):
            st.session_state.selected = source["id"]
            st.rerun()
        c1, c2, c3 = st.columns(3)
        if c1.button("↑", key=f"up_{source['id']}", disabled=i == 0):
            move_source(source["id"], -1); st.rerun()
        if c2.button("↓", key=f"down_{source['id']}", disabled=i == len(st.session_state.sources)-1):
            move_source(source["id"], 1); st.rerun()
        if c3.button("Copy", key=f"copy_{source['id']}"):
            checkpoint(); clone = deepcopy(source); clone["id"] = new_id(); clone["title"] += " (copy)"
            st.session_state.sources.insert(i + 1, clone); st.session_state.selected = clone["id"]; st.rerun()

if not st.session_state.sources:
    st.info("Upload one or more PDFs in the sidebar to begin. Use non-sensitive test documents in Community Cloud.")
    st.stop()

source = get_source(st.session_state.selected or st.session_state.sources[0]["id"])
st.session_state.selected = source["id"]

meta, editor = st.columns([0.29, 0.71], gap="large")
with meta:
    st.subheader("Selected source")
    new_title = st.text_input("Display title", source["title"], key=f"title_{source['id']}")
    new_fn = st.number_input("Footnote number", min_value=1, value=int(source["footnote"]), step=1, key=f"fn_{source['id']}")
    if new_title != source["title"] or new_fn != source["footnote"]:
        if st.button("Save source details", use_container_width=True):
            checkpoint(); source["title"] = new_title; source["footnote"] = int(new_fn); st.rerun()
    st.code(source["id"])
    st.write(f"**Pages:** {source['pages']}")
    st.write(f"**Current label:** FN {label_map()[source['id']]}")
    if st.button("Remove source", type="secondary", use_container_width=True):
        checkpoint(); st.session_state.sources = [s for s in st.session_state.sources if s["id"] != source["id"]]
        st.session_state.selected = st.session_state.sources[0]["id"] if st.session_state.sources else None
        st.rerun()

with editor:
    st.subheader("PDF annotation editor")
    page_no = st.number_input("Page", 1, source["pages"], 1, key=f"page_{source['id']}") - 1
    tool = st.radio("Tool", ["Red box", "Yellow highlight", "Text box", "Select / resize"], horizontal=True)
    note_text = st.text_area("Text for newly drawn text box", placeholder="Example: Quotation is 37 words.", disabled=tool != "Text box")
    image, pdf_w, pdf_h = render_page(source["pdf"], page_no)
    canvas_w, canvas_h = image.size
    page_key = str(page_no)
    saved = source["annotations"].get(page_key, [])
    initial = {"version": "5.3.0", "objects": [ann_to_fabric(a, canvas_w, canvas_h) for a in saved]}
    if tool == "Red box":
        mode, stroke, fill = "rect", "#ff0000", "rgba(255,0,0,0)"
    elif tool == "Yellow highlight":
        mode, stroke, fill = "rect", "#e0b000", "rgba(255,235,0,0.35)"
    elif tool == "Text box":
        mode, stroke, fill = "rect", "#8b1e3f", "rgba(255,245,248,0.45)"
    else:
        mode, stroke, fill = "transform", "#ff0000", "rgba(255,0,0,0)"
    canvas = st_canvas(
        background_image=image, initial_drawing=initial, drawing_mode=mode,
        stroke_width=3 if tool == "Red box" else 1, stroke_color=stroke, fill_color=fill,
        update_streamlit=True, height=canvas_h, width=canvas_w, display_toolbar=True,
        key=f"canvas_{source['id']}_{page_no}_{tool}",
    )
    existing_notes = [a.get("text", "") for a in saved if a["kind"] == "note"]
    c1, c2 = st.columns(2)
    if c1.button("Save this page's annotations", type="primary", use_container_width=True):
        checkpoint()
        objects = (canvas.json_data or {}).get("objects", [])
        source["annotations"][page_key] = canvas_to_annotations(objects, canvas_w, canvas_h, existing_notes, note_text)
        st.success("Annotations saved.")
    if c2.button("Clear this page", use_container_width=True):
        checkpoint(); source["annotations"][page_key] = []; st.rerun()
    st.caption("Tip: choose Select / resize to move or resize saved objects. On scanned PDFs, yellow highlighting is region-based rather than text-aware.")

st.divider()
st.subheader("Export")
st.dataframe(pd.DataFrame([{ "Order": order, "Label": label, "Source ID": s["id"], "Title": s["title"], "Pages": s["pages"] } for s, label, order in calculated_rows()]), hide_index=True, use_container_width=True)
if st.button("Build consolidated PDF and project ZIP", type="primary"):
    try:
        bundle, consolidated = build_exports()
        st.session_state["bundle"] = bundle
        st.session_state["consolidated"] = consolidated
        st.success("Export built successfully.")
    except Exception as exc:
        st.exception(exc)
if "bundle" in st.session_state:
    d1, d2 = st.columns(2)
    d1.download_button("Download project ZIP", st.session_state.bundle, "law_review_project_export.zip", "application/zip", use_container_width=True)
    d2.download_button("Download consolidated PDF", st.session_state.consolidated, "consolidated.pdf", "application/pdf", use_container_width=True)

st.warning("Prototype limitation: project state lives only in the current Streamlit session. Download exports before closing or sleeping the app. Do not use sensitive or licensed source files until private storage and authentication are added.")
