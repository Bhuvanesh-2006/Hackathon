"""Dataset Manager, Saved Queries and cache."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import requires_data

client = TestClient(app)
BUILTIN = "online_retail_ii"

SALES_CSV = (
    "Order Date,Region,Product Name,Sales Amount,Qty\n"
    "2024-01-05,North,Lamp,120.50,3\n"
    "2024-01-20,South,Desk,300.00,1\n"
    "2024-02-01,North,Lamp,80.25,2\n"
    "2024-02-03,East,Chair,99.90,4\n"
)
OTHER_CSV = (
    "Order Date,Region,Product Name,Sales Amount,Qty\n"
    "2023-06-01,West,Sofa,999.00,1\n"
)


def upload(csv_text, name, filename="data.csv", content=None):
    data = content if content is not None else csv_text.encode()
    return client.post("/api/datasets", files={"file": (filename, io.BytesIO(data), "text/csv")},
                       data={"name": name, "description": "test"})


def ask(question, dataset_id, conversation_id=None):
    return client.post("/api/agent/query", json={"question": question, "dataset_id": dataset_id,
                                                 "conversation_id": conversation_id})


# ----------------------------------------------------------------------------- imports
def test_csv_import_profiles_schema_and_preview():
    r = upload(SALES_CSV, "Shop sales")
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["status"] == "ready" and ds["row_count"] == 4 and ds["column_count"] == 5
    types = {c["name"]: c["type"] for c in ds["columns"]}
    assert types == {"order_date": "DATE", "region": "VARCHAR", "product_name": "VARCHAR",
                     "sales_amount": "DOUBLE", "qty": "BIGINT"}
    assert {c["original_name"] for c in ds["columns"]} >= {"Order Date", "Sales Amount"}
    assert "path" not in json.dumps(ds).lower() or "datasets" not in json.dumps(ds)  # no server paths exposed
    p = client.get(f"/api/datasets/{ds['id']}/preview?limit=2").json()
    assert p["columns"][0] == "order_date" and len(p["rows"]) == 2


@pytest.mark.parametrize("content,filename,status,fragment", [
    (b"", "empty.csv", 422, "empty"),
    (b"a,b\n", "header.csv", 422, "no data rows"),
    (b"a,b\n1,2,3\n4,5\n", "ragged.csv", 422, "could not be parsed"),
    (b"PK\x03\x04garbage", "fake.xlsx", 422, "Excel"),
    (b"\x00\x01\x02\x03", "binary.csv", 422, "binary"),
    (b"a,b\n1,2\n", "notes.txt", 415, "Unsupported"),
])
def test_bad_files_are_rejected_with_clear_errors(content, filename, status, fragment):
    r = upload(None, f"bad {filename}", filename, content)
    assert r.status_code == status, r.text
    assert fragment.lower() in r.json()["error"]["message"].lower()


def test_failed_new_import_is_listed_as_failed_with_errors():
    upload(None, "broken", "broken.csv", b"a,b\n")
    items = client.get("/api/datasets").json()["items"]
    failed = next(d for d in items if d["name"] == "broken")
    assert failed["status"] == "failed" and failed["errors"]


def test_duplicate_headers_mixed_types_and_encoding_are_reported_not_hidden():
    text = "Name,Name,Score,Zip\nAnn,x,10,01234\nBo,y,N/A,02345\nCé,z,12,03456\n"
    r = upload(None, "Messy", "messy.csv", text.encode("cp1252"))
    assert r.status_code == 201, r.text
    ds = r.json()
    names = [c["name"] for c in ds["columns"]]
    assert names[:2] == ["name", "name_2"]
    findings = " ".join(ds["findings"])
    assert "Duplicate column header 'Name'" in findings
    assert "not valid UTF-8" in findings
    assert "Score" in findings and "not numbers" in findings
    score = next(c for c in ds["columns"] if c["name"] == "score")
    zip_col = next(c for c in ds["columns"] if c["name"] == "zip")
    assert score["type"] == "VARCHAR" and zip_col["type"] == "VARCHAR"  # kept as text, not silently coerced


def test_xlsx_import():
    import datetime

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Day", "Store", "Units"])
    ws.append([datetime.date(2024, 3, 1), "A", 5])
    ws.append([datetime.date(2024, 3, 2), "B", 7])
    wb.create_sheet("Notes").append(["ignored"])
    buf = io.BytesIO()
    wb.save(buf)
    r = upload(None, "Excel stores", "stores.xlsx", buf.getvalue())
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["row_count"] == 2
    assert {c["name"]: c["type"] for c in ds["columns"]}["day"] in ("DATE", "TIMESTAMP")
    assert any("Other worksheets were not imported" in f for f in ds["findings"])


def test_upload_size_limit(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = upload("a\n1\n", "Too big")
    assert r.status_code in (413, 422)


def test_duplicate_dataset_name_conflicts():
    assert upload(SALES_CSV, "Same name").status_code == 201
    r = upload(SALES_CSV, "same NAME")
    assert r.status_code == 409


# ----------------------------------------------------------------------------- isolation and active dataset
def test_datasets_are_isolated_and_queries_use_selected_schema():
    a = upload(SALES_CSV, "Shop A").json()
    b = upload(OTHER_CSV, "Shop B").json()
    ra = ask("How many rows are there?", a["id"]).json()
    rb = ask("How many rows are there?", b["id"]).json()
    assert ra["status"] == rb["status"] == "success"
    assert ra["rows"][0][0] == 4 and rb["rows"][0][0] == 1
    assert ra["dataset"]["id"] == a["id"] and rb["dataset"]["id"] == b["id"]
    r = ask("What is the total sales amount by region?", a["id"]).json()
    assert r["status"] == "success" and "FROM data" in r["sql"] and "sales_amount" in r["sql"]
    assert {row[0] for row in r["rows"]} == {"North", "South", "East"}  # no West from dataset B


def test_imported_dataset_cannot_reach_other_tables():
    from app.agent.agent import answer_question
    from app.benchmarks.security import StubProvider

    a = upload(SALES_CSV, "Isolated").json()
    for sql in ["SELECT * FROM transactions", "SELECT * FROM dataset_metadata", "SELECT * FROM data; DROP TABLE data",
                "SELECT * FROM read_csv('x.csv')"]:
        r = answer_question("probe", record=False, dataset_id=a["id"], provider_override=StubProvider(sql))
        assert r["status"] == "rejected" and r["rows"] == [], sql


def test_no_invented_metrics_on_imported_dataset():
    csv = "City,Visitors\nRome,10\nParis,20\n"
    a = upload(csv, "Visits").json()
    r = ask("What was our profit?", a["id"]).json()
    assert r["status"] == "unsupported" and "does not invent" in r["answer"]


def test_active_dataset_and_conversation_binding():
    a = upload(SALES_CSV, "Active A").json()
    assert client.put("/api/datasets/active", json={"dataset_id": a["id"]}).status_code == 200
    assert client.get("/api/datasets/active").json()["active"]["id"] == a["id"]
    first = ask("How many rows are there?", a["id"]).json()
    r = ask("How many rows are there?", BUILTIN, first["conversation_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "dataset_mismatch"


def test_builtin_dataset_cannot_be_deleted_or_renamed():
    assert client.delete(f"/api/datasets/{BUILTIN}").status_code == 403
    assert client.patch(f"/api/datasets/{BUILTIN}", json={"name": "x"}).status_code == 403


def test_rename_dataset():
    a = upload(SALES_CSV, "Old name").json()
    r = client.patch(f"/api/datasets/{a['id']}", json={"name": "New 'name'; DROP TABLE data"})
    assert r.status_code == 200 and r.json()["name"] == "New 'name'; DROP TABLE data"
    assert ask("How many rows are there?", a["id"]).json()["rows"][0][0] == 4  # names are display text only


# ----------------------------------------------------------------------------- re-import, delete, cache
def test_reimport_versions_data_and_invalidates_cache():
    a = upload(SALES_CSV, "Versioned").json()
    q = client.post("/api/saved-queries", json={"title": "Rows", "sql": "SELECT COUNT(*) AS n FROM data", "dataset_id": a["id"]}).json()
    run = lambda: client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": a["id"]}).json()
    r1, r2 = run(), run()
    assert r1["rows"][0][0] == 4 and r1["execution"]["cache"]["hit"] is False
    assert r2["execution"]["cache"]["hit"] is True
    r = client.post(f"/api/datasets/{a['id']}/reimport", files={"file": ("v2.csv", io.BytesIO(OTHER_CSV.encode()), "text/csv")})
    assert r.status_code == 200 and r.json()["version"] == 2
    r3 = run()
    assert r3["execution"]["cache"]["hit"] is False and r3["rows"][0][0] == 1


def test_failed_reimport_leaves_existing_version_intact():
    a = upload(SALES_CSV, "Stable").json()
    r = client.post(f"/api/datasets/{a['id']}/reimport", files={"file": ("bad.csv", io.BytesIO(b"a,b\n1,2,3\n"), "text/csv")})
    assert r.status_code == 422 and "previous version is unchanged" in r.json()["error"]["message"]
    ds = client.get(f"/api/datasets/{a['id']}").json()
    assert ds["status"] == "ready" and ds["version"] == 1 and ds["row_count"] == 4
    assert len(client.get(f"/api/datasets/{a['id']}/preview").json()["rows"]) == 4


def test_cache_keys_are_dataset_specific_and_delete_is_isolated():
    from app.cache import get_cache

    a = upload(SALES_CSV, "Cache A").json()
    b = upload(OTHER_CSV, "Cache B").json()
    qa = client.post("/api/saved-queries", json={"title": "Rows", "sql": "SELECT COUNT(*) AS n FROM data", "dataset_id": a["id"]}).json()
    ra = client.post(f"/api/saved-queries/{qa['id']}/run", json={"dataset_id": a["id"]}).json()
    rb = client.post(f"/api/saved-queries/{qa['id']}/run", json={"dataset_id": b["id"], "allow_other_dataset": True}).json()
    assert ra["rows"][0][0] == 4 and rb["rows"][0][0] == 1  # same SQL, different dataset: never shares a result
    assert rb["execution"]["cache"]["hit"] is False
    status = get_cache().status()["per_dataset"]
    assert status.get(a["id"]) == 1 and status.get(b["id"]) == 1
    d = client.delete(f"/api/datasets/{a['id']}").json()
    assert d["saved_queries_unavailable"] == 1 and d["cache_entries_dropped"] == 1
    assert get_cache().status()["per_dataset"].get(b["id"]) == 1
    assert client.get(f"/api/datasets/{b['id']}/preview").json()["rows"][0][1] == "West"  # B untouched


# ----------------------------------------------------------------------------- saved queries
def test_saved_query_crud_duplicate_and_persistence():
    a = upload(SALES_CSV, "Library").json()
    body = {"title": "Sales by region", "question": "Total sales by region", "dataset_id": a["id"],
            "sql": "SELECT region, SUM(sales_amount) AS total FROM data GROUP BY region", "tags": ["weekly", " "],
            "category": "Geography", "description": "d"}
    r = client.post("/api/saved-queries", json=body)
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["tags"] == ["weekly"] and q["required_columns"] == ["region", "sales_amount"]
    assert client.post("/api/saved-queries", json=body).status_code == 409  # duplicate title
    assert client.patch(f"/api/saved-queries/{q['id']}", json={"title": "Regional sales"}).json()["title"] == "Regional sales"
    dup = client.post(f"/api/saved-queries/{q['id']}/duplicate", json={}).json()
    assert dup["id"] != q["id"] and dup["title"] == "Regional sales (copy)"
    # "Restart": drop in-process state; the SQLite store must still return the queries.
    from app.cache import get_cache
    from app.database import connection

    get_cache().clear()
    connection.reset_connection()
    fresh = TestClient(app)
    items = fresh.get(f"/api/saved-queries?dataset_id={a['id']}").json()["items"]
    assert {i["title"] for i in items} == {"Regional sales", "Regional sales (copy)"}
    assert all(i["compatibility"]["status"] == "compatible" for i in items)
    assert fresh.delete(f"/api/saved-queries/{dup['id']}").status_code == 200
    assert fresh.get(f"/api/saved-queries/{dup['id']}").status_code == 404


@pytest.mark.parametrize("sql", ["DROP TABLE data", "SELECT * FROM transactions", "SELECT secret FROM data"])
def test_saving_invalid_or_unsafe_sql_is_rejected(sql):
    a = upload(SALES_CSV, f"Unsafe {abs(hash(sql))}").json()
    r = client.post("/api/saved-queries", json={"title": "x", "sql": sql, "dataset_id": a["id"]})
    assert r.status_code == 422


def test_parameters_are_typed_and_cannot_inject():
    a = upload(SALES_CSV, "Params").json()
    q = client.post("/api/saved-queries", json={
        "title": "By region", "dataset_id": a["id"],
        "sql": "SELECT product_name, qty FROM data WHERE region = {{region}} LIMIT {{n}}",
        "parameters": [{"name": "region", "type": "text", "default": "North"}, {"name": "n", "type": "integer", "default": 5}]}).json()
    ok = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": a["id"], "parameters": {"region": "North", "n": 1}}).json()
    assert ok["status"] == "success" and ok["row_count"] == 1
    evil = client.post(f"/api/saved-queries/{q['id']}/run",
                       json={"dataset_id": a["id"], "parameters": {"region": "x' OR '1'='1"}}).json()
    assert evil["status"] == "empty"  # treated as a literal string, not SQL
    bad = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": a["id"], "parameters": {"n": "1; DROP"}})
    assert bad.status_code == 422
    missing = client.post("/api/saved-queries", json={"title": "y", "dataset_id": a["id"], "sql": "SELECT {{nope}} FROM data"})
    assert missing.status_code == 422


def test_incompatible_saved_query_is_not_executed_and_other_dataset_needs_confirmation():
    a = upload(SALES_CSV, "Compat A").json()
    other_schema = upload("City,Visitors\nRome,10\n", "Compat B").json()
    same_schema = upload(OTHER_CSV, "Compat C").json()
    q = client.post("/api/saved-queries", json={"title": "Totals", "dataset_id": a["id"],
                                                 "sql": "SELECT region, SUM(sales_amount) AS s FROM data GROUP BY region"}).json()
    r = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": other_schema["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "incompatible_query"
    assert set(r.json()["error"]["details"]["compatibility"]["missing_columns"]) == {"region", "sales_amount"}
    r = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": same_schema["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirmation_required"
    r = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": same_schema["id"], "allow_other_dataset": True})
    assert r.status_code == 200 and r.json()["dataset"]["id"] == same_schema["id"]


def test_recommended_queries_are_generated_from_imported_schema():
    a = upload(SALES_CSV, "Recs").json()
    data = client.get(f"/api/saved-queries?dataset_id={a['id']}").json()
    ids = {r["id"] for r in data["recommended"]}
    assert "rec_row_count" in ids and any(i.startswith("rec_monthly_") for i in ids)
    assert not any("revenue" in r["title"].lower() for r in data["recommended"])  # no column named revenue
    rid = next(i for i in ids if i.startswith("rec_top_"))
    r = client.post(f"/api/recommended-queries/{rid}/run", json={"dataset_id": a["id"]}).json()
    assert r["status"] == "success" and r["saved_query"]["builtin"] is True


@requires_data
def test_builtin_recommended_queries_validate_and_run():
    data = client.get(f"/api/saved-queries?dataset_id={BUILTIN}").json()
    assert {r["id"] for r in data["recommended"]} >= {"rec_top5_products_revenue", "rec_monthly_revenue",
                                                      "rec_best_sellers_units", "rec_sales_by_country",
                                                      "rec_top_customers", "rec_cancellations_monthly"}
    r = client.post("/api/recommended-queries/rec_top5_products_revenue/run", json={"dataset_id": BUILTIN}).json()
    assert r["status"] == "success" and r["rows"][0][0] == "22423"
    r = client.post("/api/recommended-queries/rec_top_products_in_country/run",
                    json={"dataset_id": BUILTIN, "parameters": {"country": "Germany", "top_n": 3}}).json()
    assert r["row_count"] == 3


@requires_data
def test_analyst_answer_can_be_saved_and_rerun():
    ans = ask("Which countries generated the highest revenue?", BUILTIN).json()
    assert ans["execution"]["validated"] and ans["dataset"]["id"] == BUILTIN
    q = client.post("/api/saved-queries", json={"title": "Countries", "question": ans["question"], "sql": ans["sql"],
                                                 "dataset_id": BUILTIN}).json()
    r = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": BUILTIN}).json()
    assert r["rows"] == ans["rows"]
    assert client.get(f"/api/saved-queries/{q['id']}").json()["use_count"] == 1


def test_saved_query_of_deleted_dataset_explains_why_and_is_not_run():
    a = upload(SALES_CSV, "Doomed").json()
    q = client.post("/api/saved-queries", json={"title": "Rows", "sql": "SELECT region FROM data", "dataset_id": a["id"]}).json()
    client.delete(f"/api/datasets/{a['id']}")
    item = client.get(f"/api/saved-queries/{q['id']}?dataset_id={BUILTIN}").json()
    assert item["compatibility"]["status"] == "incompatible"
    assert "has been deleted" in item["compatibility"]["reason"]
    r = client.post(f"/api/saved-queries/{q['id']}/run", json={"dataset_id": BUILTIN})
    assert r.status_code == 409


def test_malformed_placeholder_is_rejected():
    a = upload(SALES_CSV, "Braces").json()
    r = client.post("/api/saved-queries", json={"title": "b", "dataset_id": a["id"], "sql": "SELECT {{{{x}}}} FROM data",
                                                 "parameters": [{"name": "x", "type": "integer", "default": 1}]})
    assert r.status_code == 422
