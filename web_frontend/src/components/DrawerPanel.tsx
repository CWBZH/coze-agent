import { ReactNode } from "react";

type DrawerPanelProps = {
  title: string;
  children: ReactNode;
};

export function DrawerPanel({ title, children }: DrawerPanelProps) {
  return (
    <aside className="drawer-panel">
      <h3>{title}</h3>
      {children}
    </aside>
  );
}
