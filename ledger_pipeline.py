import pandas as pd
import sqlite3
from dotenv import load_dotenv
from groq import Groq
import os
import sqlglot
from sqlglot import exp
import csv
import time
from datetime import datetime

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_PATH = "logs/query_log.csv"
LOG_HEADERS = ["timestamp", "question", "sql", "retry_count", "exec_time_ms", "total_time_ms", "status"]

def _ensure_log_file():
    os.makedirs("logs", exist_ok=True)
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LOG_HEADERS)

def log_query(question, sql, retry_count, exec_time_ms, total_time_ms, status="success"):
    """Append one row to logs/query_log.csv."""
    _ensure_log_file()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            question,
            sql or "FAILED",
            retry_count,
            round(exec_time_ms, 1),
            round(total_time_ms, 1),
            status,
        ])

def csv_to_sqlite(csv_path="data/sample_expenses.csv",db_path="data/ledger.db",table_name="expenses"):

    df=pd.read_csv(csv_path)
    db_connection=sqlite3.connect(db_path)
    df.to_sql(table_name,db_connection,if_exists='replace', index=False)
    db_connection.close()
    return True

def extract_schema(db_path):
    schema={}
    db_connection=sqlite3.connect(db_path)

    tables=db_connection.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()

    for table in tables:
        table_name=table[0]

        columns= db_connection.execute(f'PRAGMA table_info({table_name})').fetchall()

        column_list=[]

        for col in columns:
            column_list.append(
                {
                    "name":col[1],
                    "type":col[2]
                }
            )
        schema[table_name]=column_list

    db_connection.close()
    return schema

def format_schema_for_prompt(schema):
    
    schema_text=""
    for table_name, columns in schema.items():
        table_line=f"Table: {table_name}"
        columns_line=[f"{col['name']} ({col['type']})" for col in columns]
        schema_text+="\n"+table_line+"\n" +", ".join(columns_line)

    return schema_text

def generate_sql(user_query, schema_text,previous_sql=None,error_message=None):
    system_message=f"""You are a SQL query generator for a SQLite database.

You will be given a database schema and a natural language question.
Generate a single, valid, read-only SQL SELECT query that answers the question.

Rules:
- Only use tables and columns that appear in the provided schema. Never invent table or column names.
- Only generate SELECT statements. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, or any other data-modifying statement.
- Use exact table and column names as given, including exact spelling and case.
- If the question is ambiguous or cannot be answered with the given schema, respond with exactly: CANNOT_ANSWER
- Return ONLY the SQL query. No explanations, no markdown formatting, no code fences, no extra text.
- For text comparisons in WHERE clauses, always use case-insensitive matching (e.g. LOWER(column) = LOWER('value') or LIKE), since the exact casing of stored values may differ from how the user phrases the question.
- For date range questions, use proper date comparison operators (>=, <, BETWEEN) on the actual date values. Never use LIKE pattern matching or SUBSTR on date strings.
- For quarter-based questions, map quarters to month ranges using CAST(strftime('%m', date) AS INTEGER): Q1 = months 1-3, Q2 = months 4-6, Q3 = months 7-9, Q4 = months 10-12. Example for Q1 of 2025: WHERE date >= '2025-01-01' AND date < '2025-04-01'. If no year is specified, use strftime('%m', date) BETWEEN '01' AND '03' for Q1, etc.

Schema:{schema_text}"""

    if previous_sql is not None and error_message is not None:
        user_message = f"""{user_query} Your previous attempt was: {previous_sql}
                        It failed with this error: {error_message}
                        Please generate a corrected query that fixes this issue."""  # include user_query, previous_sql, and error_message
    else:
        user_message = user_query

    response=client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {"role":"system","content":system_message},
        {"role":"user", "content":user_message}
    ],
    temperature=0.2
    )

    sql_query=response.choices[0].message.content
    return sql_query

def validate_sql(sql_query,schema):
    #Parsing the LLM generated query 
    try:
        parsed = sqlglot.parse_one(sql_query)
    except Exception as e:
        return (False, f"syntax error: {e}")
    tables = parsed.find_all(exp.Table)
    columns=parsed.find_all(exp.Column)

    #Checking for Tables
    for table in tables:
        if table.name not in schema.keys():
            return (False,"table not present in schema")
        
    #Checking for columns
    all_columns=set()
    for table_name,table_columns in schema.items():
        for column in table_columns:
            all_columns.add(column["name"])

    for column in columns:
        if column.name not in all_columns:
            return (False,"column not present in schema")
    
    return (True,"None")

def generate_valid_sql(user_query,schema,schema_text,max_retries=3):
    """Returns (sql_string, retry_count). sql_string is None if all retries fail."""
    previous_sql=None
    error_message=None

    for i in range(max_retries):
        candidate_sql=generate_sql(user_query,schema_text,previous_sql,error_message)
        #Tuple Unpacking-->validate_sql returns a tuple(T/F,reason)
        is_valid, error_message = validate_sql(candidate_sql, schema)
        if is_valid:
            return candidate_sql, i  # i=0 means first attempt succeeded
        previous_sql=candidate_sql

    return None, max_retries

def execute_sql(sql_query,db_path):
    connection=sqlite3.connect(f"file:{db_path}?mode=ro",uri=True)
    result=connection.execute(sql_query).fetchall()
    connection.close()
    return result

def generate_answer(user_query, sql_query, result):

    system_message=f"""You are an assistant that explains database query results in plain, natural English.

You will be given a user's question, the SQL query that was run to answer it, and the exact result of that query.

Rules:
- Only use the exact data provided in the result. Never estimate, round unnecessarily, or add numbers not present in the result.
- Answer in one or two clear sentences, as if speaking to a small business owner with no technical background.
- Do not mention SQL, databases, or technical implementation details in your answer — just state the answer naturally. """

    user_message = f"""Question: {user_query}
                       SQL Query: {sql_query}
                       Result: {result}"""
    
    response=client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role":"system","content":system_message},
            {"role":"user", "content":user_message}
        ],
        temperature=0.2
        )

    return response.choices[0].message.content


if __name__ == "__main__":
  db_path="data/ledger.db"
  schema=extract_schema(db_path)
  schema_text=format_schema_for_prompt(schema)

  question="Which category do we spend the most on?"
  sql, retries = generate_valid_sql("What is the total marketing spend?", schema, schema_text)
  result = execute_sql(sql, db_path)
  answer = generate_answer(question, sql, result)
  print(answer)