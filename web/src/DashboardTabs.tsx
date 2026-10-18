// SPDX-License-Identifier: LGPL-2.1-or-later
import type { ReactNode } from "react";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs.tsx";

export const dashboardTabs = [
  { id: "cases", label: "Cases" },
  { id: "trends", label: "Trends" },
  { id: "evidence", label: "Evidence" },
] as const;
export type DashboardTab = (typeof dashboardTabs)[number]["id"];

export function DashboardTabs({
  value,
  onChange,
  children,
  range,
}: {
  value: DashboardTab;
  onChange: (tab: DashboardTab) => void;
  children?: ReactNode;
  range?: string;
}) {
  return (
    <Tabs
      value={value}
      onValueChange={(value) => onChange(value as DashboardTab)}
    >
      <div className="view-bar">
        <TabsList variant="console" aria-label="Dashboard views">
          {dashboardTabs.map((tab, index) => (
            <TabsTrigger
              key={tab.id}
              value={tab.id}
              id={`tab-${tab.id}`}
              aria-controls={`panel-${tab.id}`}
            >
              <span className="tab-number" aria-hidden="true">
                0{index + 1}
              </span>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {range ? <span className="view-range">{range}</span> : null}
      </div>
      {children}
    </Tabs>
  );
}
