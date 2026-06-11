import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
}

export function Modal({ open, onOpenChange, title, description, children }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(32rem,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="text-lg font-semibold text-slate-900">
            {title}
          </Dialog.Title>
          {description && (
            <Dialog.Description className="mt-1 text-sm text-slate-500">
              {description}
            </Dialog.Description>
          )}
          <div className="mt-4">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
