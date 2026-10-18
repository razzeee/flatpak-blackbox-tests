// SPDX-License-Identifier: LGPL-2.1-or-later
import { useState, type ReactNode } from "react";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { Button } from "./components/ui/button.tsx";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "./components/ui/collapsible.tsx";

export function Disclosure({
  title,
  children,
}: {
  title: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="disclosure">
      <CollapsibleTrigger asChild>
        <Button variant="outline" className="disclosure-trigger">
          {title}
          <CaretDownIcon data-icon="inline-end" />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent forceMount hidden={!open}>
        <div className="disclosure-content">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}
