import sqlite3
import pytest
from ledger_pipeline import csv_to_sqlite, extract_schema, format_schema_for_prompt, validate_sql, execute_sql

SAMPLE_CSV = "data/sample_expenses.csv"

@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test_ledger.db")
    csv_to_sqlite(SAMPLE_CSV, db_path, "expenses")
    return db_path


def test_csv_to_sqlite(test_db):
    conn = sqlite3.connect(test_db)
    rows = conn.execute("SELECT * FROM expenses").fetchall()
    conn.close()
    assert len(rows) == 15


def test_extract_schema(test_db):
    schema = extract_schema(test_db)
    assert "expenses" in schema
    column_names = [col["name"] for col in schema["expenses"]]
    assert "date" in column_names
    assert "amount" in column_names


def test_format_schema_for_prompt(test_db):
    schema = extract_schema(test_db)
    schema_text = format_schema_for_prompt(schema)
    assert "Table: expenses" in schema_text
    assert "amount" in schema_text


def test_validate_sql_valid_query(test_db):
    schema = extract_schema(test_db)
    is_valid, error = validate_sql("SELECT SUM(amount) FROM expenses", schema)
    assert is_valid is True


def test_validate_sql_invalid_table(test_db):
    schema = extract_schema(test_db)
    is_valid, error = validate_sql("SELECT * FROM orders", schema)
    assert is_valid is False
    assert error == "table not present in schema"


def test_validate_sql_invalid_column(test_db):
    schema = extract_schema(test_db)
    is_valid, error = validate_sql("SELECT revenue FROM expenses", schema)
    assert is_valid is False
    assert error == "column not present in schema"


def test_validate_sql_syntax_error(test_db):
    schema = extract_schema(test_db)
    is_valid, error = validate_sql("SELEC * FROM expenses", schema)
    assert is_valid is False
    assert "syntax error" in error


def test_execute_sql_valid_query(test_db):
    result = execute_sql(
        "SELECT SUM(amount) FROM expenses WHERE LOWER(category) = LOWER('marketing')", test_db
    )
    assert result == [(2650.0,)]


def test_execute_sql_blocks_write(test_db):
    with pytest.raises(sqlite3.OperationalError):
        execute_sql("DELETE FROM expenses", test_db)