// SPDX-License-Identifier: LGPL-2.1-or-later
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { MinusIcon } from "@phosphor-icons/react/dist/csr/Minus";
import { Badge } from "./components/ui/badge.tsx";
import type { CaseStatus } from "./history.ts";
import { outcomeLabels } from "./runComparison.ts";

export function OutcomeBadge({ status }: { status?: CaseStatus }) {
  const failed = status === "failed" || status === "setup-error";
  const Icon = failed ? XIcon : status === "passed" ? CheckIcon : MinusIcon;
  return (
    <Badge variant={failed ? "destructive" : "outline"}>
      <Icon data-icon="inline-start" />
      {status ? outcomeLabels[status] : "Not recorded"}
    </Badge>
  );
}
