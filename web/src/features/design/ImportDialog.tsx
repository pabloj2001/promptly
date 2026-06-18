import { Modal } from "../../components/Modal";
import { ImportForm } from "./ImportForm";
import type { DocType } from "../../lib/types";

// Standalone import modal. Used by the project-spec empty state (fixedType =
// project_spec). The doc/task add flow imports via AddEntryDialog's Import tab.
export function ImportDialog({
  open,
  onOpenChange,
  onImported,
  fixedType = "doc",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (id: string) => void;
  fixedType?: DocType;
}) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={fixedType === "project_spec" ? "Import project spec" : "Import"}
      description="Upload one or more .md files, or paste a single document. No AI — content is saved as-is."
    >
      <ImportForm
        type={fixedType}
        onImported={(id) => {
          onOpenChange(false);
          onImported(id);
        }}
        onCancel={() => onOpenChange(false)}
      />
    </Modal>
  );
}
