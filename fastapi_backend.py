from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from ledger_pipeline import csv_to_sqlite, extract_schema, format_schema_for_prompt, generate_valid_sql, execute_sql, generate_answer

app=FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return FileResponse("index.html")

current_db_path=None
current_schema=None
current_schema_text=None

@app.post("/upload")
async def upload_data(file: UploadFile = File(...)):
    global current_db_path, current_schema, current_schema_text

    if file.filename.endswith(".csv"):
        contents = file.file.read()
        with open("data/uploaded.csv", "wb") as f:
            f.write(contents)
        csv_to_sqlite("data/uploaded.csv","data/ledger.db","expenses")

    elif file.filename.endswith(".db"):
        contents = file.file.read()
        with open("data/ledger.db","wb") as f:
            f.write(contents)
  
    schema = extract_schema("data/ledger.db")
    schema_text = format_schema_for_prompt(schema)

    current_db_path="data/ledger.db"
    current_schema=schema
    current_schema_text=schema_text
    
    return {
    "message": "upload successful",
    "tables": list(schema.keys()),
    "schema": {table: [col["name"] for col in cols] for table, cols in schema.items()}
}

@app.post("/ask")
async def ask_question(question:str = Form(...)):
    if current_db_path is None:
        return {"error": "No data uploaded yet"}

    sql_query=generate_valid_sql(question,current_schema,current_schema_text)
    if sql_query is None:
        return {"error": "Could not generate a valid query for this question."}

    result=execute_sql(sql_query,current_db_path)

    answer=generate_answer(question,sql_query,result)

    return {"answer":answer, "sql":sql_query}