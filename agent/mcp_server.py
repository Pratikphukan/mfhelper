from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DocumentMCP", log_level="ERROR")

docs = {
    "deposition.md": "This deposition covers the testimony of Angela Smith, P.E.",
    "report.pdf": "The report details the state of a 20m condenser tower.",
    "financials.docx": "These financials outline the project's budget and expenditures.",
    "outlook.pdf": "This document presents the projected future performance of the system.",
    "plan.md": "The plan outlines the steps for the project's implementation.",
    "spec.txt": "These specifications define the technical requirements for the equipment.",
}


# Write a tool to read a doc
@mcp.tool(
    name="read_doc_contents",
    description="Read the contents of a document and return it as a string"
)
def read_document(
        doc_id: str = Field(description="Id of the document to read")
):
    if doc_id not in docs:
        raise ValueError(f"{doc_id} is not a valid document")
    return docs[doc_id]


# Write a tool to edit a doc
@mcp.tool(
    name="edit_document",
    description="Edit a document by replacing a string in the documents content with a new string"
)
def edit_document(
        doc_id: str = Field(description="Id of the document that will be edited"),
        old_str: str = Field(
            description="The text to replace. Must match exactly, including whitespace"
        ),
        new_str: str = Field(
            description="The new text to insert in place of the old text"
        ),
):
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")

    docs[doc_id] = docs[doc_id].replace(old_str, new_str)


# Write a resource to return all doc id's
@mcp.resource("docs://documents")
def list_documents() -> str:
    """Returns a list of all available document IDs on the server."""
    import json
    return json.dumps(list(docs.keys()))


# Write a resource to return the contents of a particular doc
@mcp.resource("docs://documents/{doc_id}")
def get_document_content(doc_id: str) -> str:
    """Returns the raw content of a specific document on the server."""
    if doc_id not in docs:
        raise ValueError(f"Document {doc_id} not found")
    return docs[doc_id]


# Write a prompt to rewrite a doc in markdown format
@mcp.prompt()
def rewrite(doc_id: str) -> str:
    """Creates a prompt to rewrite a specific document in clean markdown format."""
    content = docs.get(doc_id, "")
    return f"Please rewrite this document in clean markdown format:\n\n{content}"


# Write a prompt to summarize a doc
@mcp.prompt()
def summarize(doc_id: str) -> str:
    """Creates a prompt to summarize a specific document."""
    content = docs.get(doc_id, "")
    return f"Please provide a concise summary of this document:\n\n{content}"


# Write a tool to analyze a mutual fund
@mcp.tool(
    name="analyze_mutual_fund",
    description="Analyze a mutual fund by its AMFI scheme code. Returns the latest NAV, distance from 52-week high, 200-day SMA, and RSI (14-day Wilder smoothing)."
)
def analyze_mutual_fund(
    scheme_code: str = Field(description="The 6-digit AMFI scheme code (e.g. '120492' for JM Flexicap)")
) -> str:
    import sys
    from pathlib import Path
    
    parent_dir = Path(__file__).resolve().parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
        
    from mfhelper.mfapi import fetch_history
    from mfhelper.metrics import distance_from_200d_sma, distance_from_52w_high, rsi as compute_rsi
    
    code = str(scheme_code).strip()
    result = fetch_history(code)
    if result is None:
        return f"Error: No NAV history found from mfapi.in for scheme code '{code}'."
        
    history = result.history
    if not history:
        return f"Error: History data is empty for scheme code '{code}'."
        
    latest_record = history[0]
    current_nav = latest_record.nav
    current_date = latest_record.nav_date
    
    dist_52w = distance_from_52w_high(history, current_nav, current_date)
    dist_200d = distance_from_200d_sma(history, current_nav, current_date)
    rsi_val = compute_rsi(history, current_nav, current_date)
    
    dist_52w_str = f"{dist_52w:.2f}%" if dist_52w is not None else "N/A"
    dist_200d_str = f"{dist_200d:.2f}%" if dist_200d is not None else "N/A (requires 200 trading days)"
    rsi_str = f"{rsi_val:.2f}" if rsi_val is not None else "N/A (requires 15 trading days)"
    
    return (
        f"Analysis for: {result.scheme_name} ({code})\n"
        f"Latest NAV: {current_nav:.4f} as of {current_date.isoformat()}\n"
        f"Distance from 52-Week High: {dist_52w_str}\n"
        f"Distance from 200-Day SMA: {dist_200d_str}\n"
        f"Relative Strength Index (RSI-14): {rsi_str}"
    )


# Write a tool to read the contents of a Google Sheet
@mcp.tool(
    name="read_google_sheet",
    description="Read the contents of your Google Sheet tab. If no tab name is provided, lists all available tab names in the spreadsheet."
)
def read_google_sheet(
    tab_name: str = Field(default="", description="The name of the worksheet tab to read (e.g. 'Daily NAV' or 'Fund Analytics'). Leave blank to list all tab names.")
) -> str:
    """Reads values from your configured Google Sheet and returns them formatted as a clean table."""
    import sys
    from pathlib import Path
    
    parent_dir = Path(__file__).resolve().parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
        
    import gspread
    from mfhelper.config import load_settings
    from mfhelper.sheets import _load_credentials
    
    settings_path = parent_dir / "config" / "settings.yaml"
    creds_path = parent_dir / "config" / "credentials.json"
    token_path = parent_dir / "data" / "token.json"
    
    try:
        settings = load_settings(settings_path)
    except Exception as e:
        return f"Error loading settings.yaml: {e}"
        
    try:
        creds = _load_credentials(creds_path, token_path)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(settings.google_sheet.spreadsheet_id)
    except Exception as e:
        return f"Error connecting to Google Sheets API: {e}. Please ensure your credentials.json is in place and you have authorized access."

    if not tab_name.strip():
        try:
            worksheets = spreadsheet.worksheets()
            names = [w.title for w in worksheets]
            return "Available worksheet tabs in your Google Sheet:\n" + "\n".join([f"- {name}" for name in names])
        except Exception as e:
            return f"Error listing worksheet tabs: {e}"

    try:
        ws = spreadsheet.worksheet(tab_name.strip())
        all_values = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        return f"Error: Worksheet tab '{tab_name}' not found. Please verify the name is correct."
    except Exception as e:
        return f"Error reading sheet contents: {e}"

    if not all_values:
        return f"Worksheet tab '{tab_name}' is currently empty."

    max_display_rows = 50
    truncated = len(all_values) > max_display_rows
    display_rows = all_values[:max_display_rows]

    lines = []
    for r_idx, row in enumerate(display_rows):
        cleaned_row = [str(cell).replace("\n", " ").strip() for cell in row]
        lines.append(" | ".join(cleaned_row))
        if r_idx == 0:
            lines.append(" | ".join(["---"] * len(row)))

    table_text = "\n".join(lines)
    if truncated:
        table_text += f"\n\n*(Table truncated: showing first {max_display_rows} of {len(all_values)} rows)*"

    return f"Contents of Google Sheet tab '{tab_name}':\n\n{table_text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
