import io
import re
import zipfile
import streamlit as st

# Resilient PyMuPDF import
try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        st.error(
            "**Missing Dependency:** PyMuPDF is not installed in this environment. "
            "Please ensure `PyMuPDF` is listed in your `requirements.txt` and reboot the app."
        )
        st.stop()

st.set_page_config(
    page_title="Law Review Footnote & Annotation Portal", layout="wide"
)


# --- CORE UTILITIES ---
def extract_id_from_pdf(pdf_bytes: bytes) -> str:
    """Scans Page 1 text & annotations for 3-letter + digit IDs (e.g., SUS1, CUC12)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) == 0:
        return ""

    page = doc[0]

    # Search visible text
    text = page.get_text()
    match = re.search(r"\b([A-Z]{3}\d+)\b", text)
    if match:
        return match.group(1)

    # Search annotations
    for annot in page.annots():
        info = annot.info
        content = (info.get("content") or "") + " " + (info.get("title") or "")
        match = re.search(r"\b([A-Z]{3}\d+)\b", content)
        if match:
            return match.group(1)

    return ""


def calculate_labels(source_list: list[dict]) -> list[dict]:
    """Calculates footnote notation (e.g., Footnote 1 with 2 sources -> '1.1', '1.2')."""
    fn_counts = {}
    for item in source_list:
        fn = item["footnote"]
        fn_counts[fn] = fn_counts.get(fn, 0) + 1

    fn_current_sub = {}
    updated_sources = []

    for item in source_list:
        fn = item["footnote"]
        total = fn_counts[fn]

        if total == 1:
            label = f"{fn}"
        else:
            fn_current_sub[fn] = fn_current_sub.get(fn, 0) + 1
            label = f"{fn}.{fn_current_sub[fn]}"

        item_copy = item.copy()
        item_copy["label"] = label
        updated_sources.append(item_copy)

    return updated_sources


def apply_annotations_and_stamp(
    pdf_bytes: bytes,
    label_text: str,
    highlight_text: str = "",
    editor_note: str = "",
    add_red_box: bool = False,
) -> bytes:
    """Stamps dynamic footnote label, highlights text, draws red boxes, and overlays custom notes."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]

    # 1. Top-Right Footnote Label Box
    rect = fitz.Rect(page.rect.width - 130, 15, page.rect.width - 15, 45)
    page.draw_rect(rect, color=(0.1, 0.2, 0.5), fill=(1, 1, 1), width=1.5)
    page.insert_textbox(
        rect,
        f"FN {label_text}",
        fontsize=11,
        fontname="helv",
        color=(0.1, 0.2, 0.5),
        align=fitz.TEXT_ALIGN_CENTER,
    )

    # 2. Text Search & Yellow Highlight
    if highlight_text.strip():
        matches = page.search_for(highlight_text.strip())
        for match in matches:
            annot = page.add_highlight_annot(match)
            annot.set_colors(stroke=(1, 0.8, 0))
            annot.update()

    # 3. Outer Red Boundary Box
    if add_red_box:
        margin_rect = fitz.Rect(
            20, 20, page.rect.width - 20, page.rect.height - 20
        )
        page.draw_rect(margin_rect, color=(0.8, 0.1, 0.1), width=2.0)

    # 4. Custom Editor Overlay Note
    if editor_note.strip():
        note_rect = fitz.Rect(20, 50, 250, 85)
        page.draw_rect(
            note_rect, color=(0.8, 0.1, 0.1), fill=(1, 0.95, 0.95), width=1.0
        )
        page.insert_textbox(
            note_rect,
            f"NOTE: {editor_note.strip()}",
            fontsize=9,
            fontname="helv",
            color=(0.8, 0.1, 0.1),
            align=fitz.TEXT_ALIGN_LEFT,
        )

    output_bytes = doc.write()
    doc.close()
    return output_bytes


# --- APP INTERFACE ---
st.title("📚 Law Review Source Annotation & Renumbering Portal")
st.markdown(
    "Upload raw source PDFs, assign footnote numbers, add highlights/editor notes/red boxes, and export stamped PDFs instantly."
)

# Step 1: Upload Files
uploaded_files = st.file_uploader(
    "Upload Source PDFs", type=["pdf"], accept_multiple_files=True
)

if uploaded_files:
    if "sources" not in st.session_state or st.sidebar.button("Re-scan Uploads"):
        sources = []
        for file in uploaded_files:
            b = file.read()
            extracted_id = extract_id_from_pdf(b)
            sources.append(
                {
                    "filename": file.name,
                    "bytes": b,
                    "id": extracted_id if extracted_id else "UNKNOWN",
                    "footnote": 1,
                }
            )
        st.session_state.sources = sources

    st.subheader("Step 2: Assign Footnotes & Annotation Settings")

    # Global Batch Annotation Controls
    with st.expander("🛠️ Advanced Annotation Settings (Apply to PDFs)", expanded=True):
        col_a, col_b, col_c = st.columns([2, 2, 1])
        with col_a:
            highlight_query = st.text_input(
                "Text to Auto-Highlight (Yellow)",
                placeholder="e.g., supra note 5",
            )
        with col_b:
            custom_note = st.text_input(
                "Editor Overlay Note", placeholder="e.g., Verified Pinpoint Page"
            )
        with col_c:
            st.write("")
            st.write("")
            draw_box = st.checkbox("Add Red Border Box")

    st.write("**Set Footnote Numbers for Sources:**")
    edited_data = []

    for idx, item in enumerate(st.session_state.sources):
        c1, c2, c3 = st.columns([3, 2, 2])
        with c1:
            st.text(f"📄 {item['filename']}")
        with c2:
            tag_id = st.text_input(
                "ID",
                value=item["id"],
                key=f"id_{idx}",
                label_visibility="collapsed",
            )
        with c3:
            fn_num = st.number_input(
                "Footnote #",
                min_value=1,
                value=item["footnote"],
                step=1,
                key=f"fn_{idx}",
                label_visibility="collapsed",
            )

        edited_data.append(
            {
                "filename": item["filename"],
                "bytes": item["bytes"],
                "id": tag_id,
                "footnote": fn_num,
            }
        )

    # Sequence and calculate numbers
    sorted_sources = sorted(edited_data, key=lambda x: x["footnote"])
    processed_sources = calculate_labels(sorted_sources)

    st.divider()
    st.subheader("Step 3: Output Preview")

    grid_cols = st.columns(min(len(processed_sources), 4))
    for idx, src in enumerate(processed_sources):
        with grid_cols[idx % 4]:
            st.metric(
                label=f"ID: {src['id']}",
                value=f"FN {src['label']}",
                delta=src["filename"],
            )

    st.divider()
    st.subheader("Step 4: Download Renumbered & Annotated PDFs")

    if st.button("Generate & Package Stamped PDFs"):
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(
            zip_buffer, "a", zipfile.ZIP_DEFLATED, False
        ) as zip_file:
            for src in processed_sources:
                stamped_bytes = apply_annotations_and_stamp(
                    pdf_bytes=src["bytes"],
                    label_text=src["label"],
                    highlight_text=highlight_query,
                    editor_note=custom_note,
                    add_red_box=draw_box,
                )
                clean_name = (
                    f"FN_{src['label'].replace('.', '_')}_{src['id']}.pdf"
                )
                zip_file.writestr(clean_name, stamped_bytes)

        st.success("All PDFs annotated, renumbered, and stamped!")
        st.download_button(
            label="📦 Download All (.ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Law_Review_Renumbered_Sources.zip",
            mime="application/zip",
        )
