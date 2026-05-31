import json
import sqlite3

from web_api.services.observability_service import ObservabilityService
from web_api.services.sqlite_readonly import ReadOnlySqlite


def _create_observability_db(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE pdd_inbound_message_queue (
                id TEXT PRIMARY KEY,
                trace_id TEXT,
                shop_id TEXT,
                user_id TEXT,
                buyer_id TEXT,
                session_id TEXT,
                message_type TEXT,
                payload_json TEXT,
                status TEXT,
                retry_count INTEGER,
                error_type TEXT,
                created_at REAL,
                updated_at REAL
            );

            CREATE TABLE pdd_reply_outbox (
                id TEXT PRIMARY KEY,
                inbound_record_id TEXT,
                trace_id TEXT,
                shop_id TEXT,
                user_id TEXT,
                buyer_id TEXT,
                session_id TEXT,
                reply_action TEXT,
                reply_text TEXT,
                reply_source TEXT,
                status TEXT,
                retry_count INTEGER,
                max_retries INTEGER,
                next_retry_at REAL,
                last_attempt_at REAL,
                pdd_error_code TEXT,
                reply_hash TEXT,
                reply_length INTEGER,
                error_summary_hash TEXT,
                created_at REAL,
                updated_at REAL
            );
            """
        )


def test_trace_nodes_use_final_result_intent_when_trace_payload_omits_classifier_status(tmp_path, monkeypatch):
    trace_id = "pdd:565617:1780203732137"
    db_path = tmp_path / "channel_shop.db"
    _create_observability_db(db_path)

    payload = {
        "content": "什么时候发货",
        "message_type": "text",
        "source_message_id": "1780203732137",
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pdd_inbound_message_queue
            (id, trace_id, shop_id, user_id, buyer_id, session_id, message_type, payload_json, status, retry_count, error_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "inbound-1",
                trace_id,
                "565617",
                "713439",
                "6554248824766",
                "565617_6554248824766",
                "text",
                json.dumps(payload, ensure_ascii=False),
                "done",
                0,
                "",
                1780203732.0,
                1780203733.0,
            ),
        )
        conn.execute(
            """
            INSERT INTO pdd_reply_outbox
            (id, inbound_record_id, trace_id, shop_id, user_id, buyer_id, session_id, reply_action, reply_text, reply_source, status, retry_count, max_retries, next_retry_at, last_attempt_at, pdd_error_code, reply_hash, reply_length, error_summary_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "outbox-1",
                "inbound-1",
                trace_id,
                "565617",
                "713439",
                "6554248824766",
                "565617_6554248824766",
                "reply",
                "亲亲，默认极兔速递，48小时内广州发货，具体以订单物流页为准",
                "reply",
                "reply_sent",
                0,
                3,
                0,
                1780203733.0,
                "",
                "hash-1",
                32,
                "",
                1780203732.5,
                1780203733.0,
            ),
        )

    trace_dir = tmp_path / "debug_traces"
    trace_dir.mkdir()
    (trace_dir / "pdd_565617_1780203732137.json").write_text(
        json.dumps(
            {
                "events": {
                    "rag": {
                        "query": "什么时候发货",
                        "hits": [
                            {
                                "chunk_id": "kc:565617:8:test",
                                "domain": "logistics_policy",
                                "source_type": "sop",
                                "source_id": "2",
                                "content": "默认极兔速递，48小时内广州发货。",
                                "score": 0.01,
                            }
                        ],
                    },
                    "answer_generation_input": {
                        "conversation_text": "买家：什么时候发货",
                        "context_blocks": ["默认极兔速递，48小时内广州发货。"],
                        "prompt_hash": "prompt-hash",
                    },
                    "answer_generation_output": {
                        "answer_text": "亲亲，默认极兔速递，48小时内广州发货，具体以订单物流页为准",
                    },
                    "final_result": {
                        "intent": "logistics_order_status",
                        "action": "reply",
                        "guardrail_status": "safe",
                        "reply_text": "亲亲，默认极兔速递，48小时内广州发货，具体以订单物流页为准",
                        "trace": {
                            "product_context_status": "resolved",
                            "rag_status": "hit",
                            "prompt_hash": "prompt-hash",
                            "calls_llm": True,
                            "answer_generation_status": "ok",
                        },
                    },
                    "send_completed": {
                        "final_status": "reply_sent",
                        "reply_text": "亲亲，默认极兔速递，48小时内广州发货，具体以订单物流页为准",
                        "send_ms": 416,
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE_DIR", str(trace_dir))

    result = ObservabilityService(ReadOnlySqlite(db_path)).get_trace(trace_id)

    nodes = {node["key"]: node for node in result["nodes"]}
    assert result["reply_generation"]["intent"] == "logistics_order_status"
    assert result["reply_generation"]["calls_llm"] is True
    assert result["intent_evidence"]["intent"] == "logistics_order_status"
    assert result["intent_evidence"]["status"] == "ok"
    assert result["intent_evidence"]["source_label"] == "InternalEngine 流程/规则识别"
    assert result["send_text"] == "亲亲，默认极兔速递，48小时内广州发货，具体以订单物流页为准"
    assert nodes["intent"]["status"] == "passed"
    assert "logistics_order_status" in nodes["intent"]["summary"]
    assert "未调用独立分类器" in nodes["intent"]["summary"]
    assert nodes["llm"]["status"] == "passed"
    assert nodes["guardrail"]["status"] == "passed"
    assert nodes["pdd_send"]["status"] == "passed"
