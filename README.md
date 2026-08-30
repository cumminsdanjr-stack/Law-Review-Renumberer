# Law Review PDF Workspace Prototype

A Streamlit prototype for organizing source PDFs by footnote, drawing editable red boxes, adding region highlights and free-form note boxes, and exporting a consolidated annotated PDF.

## What the prototype does

- Upload multiple PDFs
- Generate automatic immutable source IDs
- Assign footnote numbers
- Reorder and duplicate sources
- Display calculated labels such as `1`, `2.1`, and `2.2`
- Draw transparent red proposition boxes
- Draw yellow region highlights, including over scanned pages
- Draw free-form text-box regions
- Move and resize saved annotations
- Undo and redo saved project changes
- Export an editable annotated consolidated PDF
- Export separate PDFs plus JSON and CSV manifests in a ZIP

## Important prototype limitations

- State is held in the active Streamlit session and is not durable.
- Streamlit Community Cloud should be tested only with non-sensitive documents.
- Highlighting is region-based. True browser text-selection highlights require a dedicated PDF.js component.
- Undo and redo apply to saved changes, not every unsaved mouse movement.
- The original uploaded PDFs are never modified.

## Deploy on Streamlit Community Cloud

1. Create a new GitHub repository.
2. Upload these files to its root:
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `.streamlit/config.toml`
3. Open https://share.streamlit.io and select **Create app**.
4. Select the repository and branch.
5. Set the main file path to `app.py`.
6. In Advanced settings, choose a supported Python version, preferably Python 3.12.
7. Deploy.
8. Watch the build logs until the app starts.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

## Suggested test

1. Upload two small public-domain PDFs.
2. Set both to Footnote 1 and verify labels `1.1` and `1.2`.
3. Duplicate one source and move it to Footnote 2.
4. Draw a red box on page 1 and save.
5. Choose **Select / resize**, adjust the box, and save again.
6. Draw a yellow region highlight on another page.
7. Draw a text-box region and enter a free-form note.
8. Export and inspect `consolidated.pdf` and `manifest.json`.
