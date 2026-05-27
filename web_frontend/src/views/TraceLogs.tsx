import { useEffect, useState } from "react";

import { getTrace, getTraces, TraceSummary } from "../api/traces";
import { DataTable } from "../components/DataTable";
import { DrawerPanel } from "../components/DrawerPanel";
import { StatusBadge } from "../components/StatusBadge";

export function TraceLogs() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    getTraces().then((data) => {
      setTraces(data.items);
      if (data.items[0]) getTrace(data.items[0].trace_id).then(setDetail);
    });
  }, []);

  return (
    <div className="content-grid detail-layout">
      <section className="panel">
        <div className="page-intro">
          <h2>调试日志</h2>
          <p>
            用于查看 AI 回复链路的调试信息，包括 intent、RAG、LLM、guardrail、active version 和最终状态。
            这里展示的是排查用业务信息，不展示密钥凭证。
          </p>
        </div>
        <div className="panel-header">
          <h2>链路记录</h2>
          <div className="filters">
            <input placeholder="trace_id / buyer_id / session_id" />
            <select><option>全部意图</option></select>
            <select><option>仅错误</option></select>
          </div>
        </div>
        <DataTable<TraceSummary>
          rows={traces}
          onRowClick={(row) => getTrace(row.trace_id).then(setDetail)}
          columns={[
            { key: "time", label: "时间" },
            { key: "trace_id", label: "trace_id" },
            { key: "shop_id", label: "店铺 shop_id" },
            { key: "buyer_id", label: "buyer_id" },
            { key: "session_id", label: "session_id" },
            { key: "intent", label: "意图 intent" },
            { key: "domain", label: "领域 domain" },
            { key: "action", label: "动作 action" },
            { key: "rag_hit_count", label: "RAG 命中" },
            { key: "final_status", label: "最终状态 final_status" },
            { key: "no_send", label: "不发送 no_send", render: (row) => <StatusBadge tone="info">{row.no_send}</StatusBadge> }
          ]}
        />
      </section>
      <DrawerPanel title="Trace 详情">
        {detail ? <pre>{JSON.stringify(detail, null, 2)}</pre> : null}
      </DrawerPanel>
    </div>
  );
}
