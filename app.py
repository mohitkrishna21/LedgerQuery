import gradio as gr
from ledger_pipeline import csv_to_sqlite, extract_schema, format_schema_for_prompt, generate_valid_sql, execute_sql, generate_answer

current_db_path = None
current_schema = None
current_schema_text = None

def handle_upload(file):
    global current_db_path, current_schema, current_schema_text
    if file.endswith(".csv"):
        csv_to_sqlite(file, "data/ledger.db", "expenses")
        db_path = "data/ledger.db"
    elif file.endswith(".db"):
        db_path = file
    schema = extract_schema(db_path)
    schema_text = format_schema_for_prompt(schema)
    current_db_path = db_path
    current_schema = schema
    current_schema_text = schema_text
    tables = list(schema.keys())
    return f"Ready — tables loaded: {', '.join(tables)}"

def handle_question(question, history):
    if not question.strip():
        return history, ""
    if current_db_path is None:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": "No data uploaded yet. Please upload a file first."})
        return history, ""
    sql_query = generate_valid_sql(question, current_schema, current_schema_text)
    if sql_query is None:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": "Could not generate a valid SQL query for this question."})
        return history, ""
    result = execute_sql(sql_query, current_db_path)
    answer = generate_answer(question, sql_query, result)
    assistant_content = f"**SQL:** `{sql_query}`\n\n**Answer:** {answer}"
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": assistant_content})
    return history, ""

css = """
body { background-color: #f0f2f8; }

.left-panel {
    background: white;
    border-radius: 16px;
    padding: 24px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    height: 100%;
}

.right-panel {
    background: white;
    border-radius: 16px;
    padding: 24px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    height: 100%;
}

.app-title {
    font-size: 1.6rem !important;
    font-weight: 700 !important;
    color: #1a1a2e !important;
    margin-bottom: 4px !important;
}

.app-subtitle {
    color: #666 !important;
    font-size: 0.85rem !important;
    margin-bottom: 24px !important;
}

.upload-btn {
    background: #4f46e5 !important;
    border: none !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}

.ask-btn {
    background: #4f46e5 !important;
    border: none !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    min-width: 80px !important;
}

.status-box textarea {
    background: #f8f9ff !important;
    border: 1px solid #e0e4ff !important;
    border-radius: 8px !important;
    color: #4f46e5 !important;
    font-size: 0.85rem !important;
}

footer { display: none !important; }
"""

with gr.Blocks(css=css, title="LedgerQuery") as demo:
    with gr.Row(equal_height=True):

        # ── LEFT: Upload panel ──────────────────────────────────────
        with gr.Column(scale=1, elem_classes="left-panel"):
            gr.Markdown("## LedgerQuery", elem_classes="app-title")
            gr.Markdown("Natural language Q&A for your financial data.", elem_classes="app-subtitle")

            file_input = gr.File(
                label="Upload CSV or SQLite DB",
                file_types=[".csv", ".db"]
            )
            upload_button = gr.Button("Upload", elem_classes="upload-btn")
            upload_status = gr.Textbox(
                label="Status",
                interactive=False,
                placeholder="Waiting for upload...",
                elem_classes="status-box"
            )

        # ── RIGHT: Q&A panel ────────────────────────────────────────
        with gr.Column(scale=2, elem_classes="right-panel"):
            chatbot = gr.Chatbot(
                label="Session History",
                height=520,
                show_label=True
            )
            with gr.Row():
                question_input = gr.Textbox(
                    label="",
                    placeholder="Ask a question about your data...",
                    scale=5,
                    lines=1
                )
                ask_button = gr.Button("Ask", elem_classes="ask-btn", scale=1)

    upload_button.click(fn=handle_upload, inputs=file_input, outputs=upload_status)
    ask_button.click(fn=handle_question, inputs=[question_input, chatbot], outputs=[chatbot, question_input])
    question_input.submit(fn=handle_question, inputs=[question_input, chatbot], outputs=[chatbot, question_input])

demo.launch()