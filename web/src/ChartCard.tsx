// SPDX-License-Identifier: LGPL-2.1-or-later
import type { ReactNode } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "./components/ui/card.tsx";

export function ChartCard({
  title,
  description,
  children,
  legend,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  legend?: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle role="heading" aria-level={3}>
          {title}
        </CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
      {legend ? <CardFooter>{legend}</CardFooter> : null}
    </Card>
  );
}
