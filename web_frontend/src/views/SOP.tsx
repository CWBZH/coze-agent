import { useEffect, useState } from "react";

import { getSopDetail, getSopRecords, SopDetail, SopRecord } from "../api/sop";
import { DataTable } from "../components/DataTable";
import { DrawerPanel } from "../components/DrawerPanel";
import { StatusBadge } from "../components/StatusBadge";

const domains = ["商品目录", "物流履约", "售后取证", "优惠活动", "敏感人群安全", "红线转人工"];

export function SOP() {
  const [records, setRecords] = useState<SopRecord[]>([]);
  const [detail, setDetail] = useState<SopDetail | null>(null);

  useEffect(() => {
    getSopRecords().then((data) => {
      setRecords(data.items);
      if (data.items[0]) getSopDetail(data.items[0].id).then(setDetail);
    });
  }, []);

  return (
    <div className="sop-layout">
      <section className="panel domain-list">
        <h2>SOP 领域</h2>
        <p className="muted">旧版 SOP 查看页。完整草稿、发布和索引闭环请使用“知识中心”。</p>
        {domains.map((domain) => <button key={domain}>{domain}</button>)}
      </section>
      <section className="panel">
        <h2>SOP 管理</h2>
        <p className="muted">用于查看 SOP 内容、状态和索引情况。保存草稿、发布版本请前往知识中心。</p>
        <DataTable<SopRecord>
          rows={records}
          onRowClick={(row) => getSopDetail(row.id).then(setDetail)}
          columns={[
            { key: "title", label: "标题" },
            { key: "domain", label: "领域 domain" },
            { key: "version", label: "版本" },
            { key: "status", label: "状态" },
            { key: "indexed", label: "已索引", render: (row) => <StatusBadge tone={row.indexed ? "success" : "warning"}>{row.indexed}</StatusBadge> },
            { key: "updated_at", label: "updated_at" }
          ]}
        />
      </section>
      <DrawerPanel title="SOP 详情">
        {detail ? (
          <div className="detail-stack">
            <strong>{detail.title}</strong>
            <span>SOP id: {detail.id}</span>
            <span>状态 status: {detail.status}</span>
            <span>版本 version: {detail.version}</span>
            <span>是否索引 indexed: {String(detail.indexed)}</span>
            <textarea value={detail.content} readOnly rows={12} />
            <button>重新索引</button>
            <button>发布</button>
          </div>
        ) : null}
      </DrawerPanel>
    </div>
  );
}
