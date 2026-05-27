import { ReactNode } from "react";

type DataTableProps<T> = {
  columns: Array<{ key: keyof T | string; label: string; render?: (row: T) => ReactNode }>;
  rows: T[];
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
};

export function DataTable<T extends object>({ columns, rows, emptyMessage = "No data", onRowClick }: DataTableProps<T>) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={String(column.key)}>{column.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td className="empty-table-cell" colSpan={columns.length}>{emptyMessage}</td>
          </tr>
        ) : (
          rows.map((row, index) => (
            <tr key={index} onClick={() => onRowClick?.(row)}>
              {columns.map((column) => (
                <td key={String(column.key)}>
                  {column.render ? column.render(row) : String((row as Record<string, unknown>)[String(column.key)] ?? "")}
                </td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
