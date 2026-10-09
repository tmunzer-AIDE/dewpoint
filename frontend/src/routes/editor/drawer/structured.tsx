// SPDX-License-Identifier: Apache-2.0
// A value made of parts (4c-1, ruling 5): a group's properties, each a field of its own.
import { propertiesOf, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { segment } from "./context";
import { FieldView } from "./FieldView";

/** The widgets shown as their parts rather than as one control. */
export const isContainer = (widget: Widget): boolean => widget === "group";

/** The pointer segments of the parts a container shows: a problem below it in any other part is its own. */
export const partNames = (spec: FieldSpec): string[] => propertiesOf(spec).map((p) => segment(p.name));

export function ContainerParts({ spec }: { spec: FieldSpec }) {
  return propertiesOf(spec).map((part) => <FieldView key={part.pointer} spec={part} />);
}
