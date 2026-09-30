"""Independent A-C regression expectations; synthetic SQLite only."""
import json
import sqlite3
import subprocess
import sys

import pytest
from test_core import record
from test_review_f99 import snapshot
from test_rust_repair import binary as rust_binary_fixture
from test_rust_repair import invoke

from sakura_knowledge.api import Knowledge

binary = rust_binary_fixture


def payload_db(tmp_path, payload):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT json_valid(?)", (payload,)).fetchone()[0] == 1
        conn.execute("UPDATE entry_evidence SET payload=?", (payload,))
    conn.close()  # immutable readers must see checkpointed fixture bytes
    return db


@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("ignored", [False, True])
def test_a_5001_digit_integer(binary, tmp_path, negative, ignored):
    number = ("-" if negative else "") + "1" + "0" * 5000
    payload = ('{"raw":{"ignored":'+number+',"raw_gender":"simple"}}' if ignored else
               '{"raw":{"raw_gender":'+number+'}}')
    db = payload_db(tmp_path, payload)
    guard = sys.get_int_max_str_digits()
    with Knowledge(db) as api:
        python = api.lookup("hero")
    rust = invoke(binary, "lookup", db, "hero")
    for result in (python, rust):
        field = result["source_fields"]["raw_gender"][0]
        assert result["status"] == "found"
        assert field["value"] == ("simple" if ignored else None)
        assert field["truncated"] == (not ignored)
        assert field["value_state"] == "present"
    assert python == rust
    assert sys.get_int_max_str_digits() == guard
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT payload FROM entry_evidence").fetchone()[0] == payload


@pytest.mark.parametrize("lexeme,wanted,truncated", [
    ("1."+"0"*2050, 1.0, False),
    ("-1."+"0"*2050, -1.0, False),
    ("1e+"+"0"*2050, 1.0, False),
    ("1."+"0"*2050+"e2", 100.0, False),
    ("1e9999", None, True),
    ("-1e9999", None, True),
    ("1e-9999", 0.0, False),
], ids=["long_decimal", "negative_long_decimal", "long_exponent", "decimal_exponent",
        "overflow", "negative_overflow", "underflow"])
def test_b_float_projected_budget(binary, tmp_path, lexeme, wanted, truncated):
    payload = '{"raw":{"raw_gender":'+lexeme+'}}'
    db = payload_db(tmp_path, payload)
    with Knowledge(db) as api:
        python = api.lookup("hero")
    rust = invoke(binary, "lookup", db, "hero")
    for result in (python, rust):
        field = result["source_fields"]["raw_gender"][0]
        assert field["value"] == wanted
        assert field["truncated"] == truncated
        assert field["value_state"] == "present"
    assert python == rust
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT payload FROM entry_evidence").fetchone()[0] == payload


@pytest.mark.parametrize("lexeme", ["NaN", "Infinity", "1e", "01"])
def test_b_invalid_json_rejected(binary, tmp_path, lexeme):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    payload = '{"raw":{"raw_gender":'+lexeme+'}}'
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT json_valid(?)", (payload,)).fetchone()[0] == 0
        conn.execute("UPDATE entry_evidence SET payload=?", (payload,))
    conn.close()  # immutable readers must see checkpointed fixture bytes
    with Knowledge(db) as api, pytest.raises(ValueError):
        api.lookup("hero")
    proc = subprocess.run([str(binary), "lookup", str(db), "hero"], capture_output=True, timeout=15, check=False)
    assert proc.returncode == 2 and not proc.stdout


@pytest.mark.parametrize("huge", [False, True])
def test_c_inspect_total_response_cap(binary, tmp_path, huge):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    identity = "s" * (600000 if huge else 16)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE build_meta SET value=? WHERE key='snapshot'", (identity,))
    conn.close()
    with Knowledge(db) as api:
        if huge:
            with pytest.raises(ValueError, match="response_budget_exceeded"):
                api.inspect()
        else:
            expected = api.inspect()
            assert expected["snapshot"] == identity
    proc = subprocess.run([str(binary), "inspect", str(db)], capture_output=True, timeout=15, check=False)
    if huge:
        assert proc.returncode == 2 and not proc.stdout
        assert json.loads(proc.stderr)["message"] == "response_budget_exceeded"
    else:
        assert proc.returncode == 0 and len(proc.stdout) <= 524289
        assert json.loads(proc.stdout) == expected
