import io
import re
import zipfile
import streamlit as st
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

st.set_page_config(
    page_title="Law Review Footnote & Annotation Portal", layout="wide"
)

# --- CORE UTILITIES ---
def extract_id_from_pdf(pdf_bytes: bytes) -> str:
    """Scans Page 1 text for 3-letter + digit IDs (e.g., SUS1, CUC12) using pypdf."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return ""
        
        text = reader.pages[0].extract_text()
        match = re.search(r"\b([A-Z]{3}\d+)\b", text)
        if match:
            return match.group(1)
    except Exception:
        pass
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

def apply_annotations(
    pdf_bytes: bytes,
    label_text: str,
    editor_note: str = "",
    add_red_box: bool = False,
) -> bytes:
    """Generates an overlay PDF using reportlab and merges it onto the original PDF."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    
    # Target the first page
    page = reader.pages[0]
    
    # Get dimensions (convert to float for ReportLab)
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    
    # Create the overlay canvas in memory
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(width, height))
    
    # 1. Draw Outer Red Boundary Box
    if add_red_box:
        c.setStrokeColorRGB(0.8, 0.1, 0.1) # Red
        c.setLineWidth(2.0)
        # x, y, width, height (ReportLab starts 0,0 at bottom left)
        c.rect(20, 20, width - 40, height - 40, fill=0)

    # 2. Draw Top-Right Footnote Label Box
    stamp_w, stamp_h = 115, 30
    stamp_x = width - stamp_w - 15
    stamp_y = height - stamp_h - 15
    
    c.setFillColorRGB(1, 1, 1) # White fill
    c.setStrokeColorRGB(0.1, 0.2, 0.5) # Navy border
    c.setLineWidth(1.5)
    c.rect(stamp_x, stamp_y, stamp_w, stamp_h, fill=1, stroke=1)
    
    # Add text to stamp
    c.setFillColorRGB(0.1, 0.2, 0.5)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(stamp_x + (stamp_w / 2), stamp_y + 10, f"FN {label_text}")

    # 3. Custom Editor Overlay Note
    if editor_note.strip():
        note_w, note_h = 250, 35
        note_x = 20
        note_y = height - note_h - 50 # Near the top left margin
        
        c.setFillColor(Color(1, 0.95, 0.95)) # Light red fill
        c.setStrokeColorRGB(0.8, 0.1, 0.1) # Red border
        c.setLineWidth(1.0)
        c.rect(note_x, note_y, note_w, note_h, fill=1, stroke=1)
        
        c.setFillColorRGB(0.8, 0.1, 0.1)
        c.setFont("Helvetica", 9)
        # Simple text placement inside the box
        c.drawString(note_x + 10, note_y + 12, f"NOTE: {editor_note.strip()}")

    # Save the overlay
    c.save()
    packet.seek(0)
    
    # Merge the overlay onto the original page
    overlay_pdf = PdfReader(packet)
    page.merge_page(overlay_pdf.pages[0])
    writer.add_page(page)
    
    # Copy the remaining pages untouched
    for i in range(1, len(reader.pages)):
        writer.add_page(reader.pages[i])
        
    output_bytes = io.BytesIO()
    writer.write(output_bytes)
    return output_bytes.getvalue()

# --- APP INTERFACE ---
st.title("📚 Law Review Source Annotation & Renumbering Portal")
st.markdown(
    "Upload raw source PDFs, assign footnote numbers, add editor notes/red boxes, and export stamped PDFs instantly."
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
        col_a, col_b = st.columns([3, 1])
        with col_a:
            custom_note = st.text_input(
                "Editor Overlay Note", placeholder="e.g., Verified Pinpoint Page"
            )
        with col_b:
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
                stamped_bytes = apply_annotations(
                    pdf_bytes=src["bytes"],
                    label_text=src["label"],
                    editor_note=custom_note,
                    add_red_box=draw_box,
                )
                clean_name = f"FN_{src['label'].replace('.', '_')}_{src['id']}.pdf"
                zip_file.writestr(clean_name, stamped_bytes)

        st.success("All PDFs annotated, renumbered, and stamped!")
        st.download_button(
            label="📦 Download All (.ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Law_Review_Renumbered_Sources.zip",
            mime="application/zip",
        )
