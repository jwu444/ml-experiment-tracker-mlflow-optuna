import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import styles from "./Dialog.module.css";

export interface DialogProps {
  trigger: ReactNode;
  title: string;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/** Gap kept between a pinned dialog and the viewport edge. */
const MARGIN = 12;

/** Centring by `transform: translate(-50%, -50%)` and resizing by drag handle
 *  fight each other: growing such a box shifts it back by half of what it grew,
 *  so the corner crawls away at half the pointer's speed. The dialog is
 *  therefore centred by CSS once, measured on mount, and then pinned to those
 *  pixel coordinates — after which the handle tracks the pointer exactly.
 *
 *  Pinning also fixes where the box's top-left corner is, so the max size is
 *  recomputed from there: without it, dragging down-right pulls the dialog's own
 *  bottom edge off-screen, where nothing can scroll it back into view. */
function pinForResize(node: HTMLDivElement | null) {
  if (!node) return;
  const rect = node.getBoundingClientRect();
  // jsdom reports 0×0 for everything. Pinning an unmeasured element to (0, 0)
  // would discard the CSS centring, so leave it alone.
  if (rect.width === 0 && rect.height === 0) return;
  const top = Math.max(rect.top, MARGIN);
  const left = Math.max(rect.left, MARGIN);
  node.style.transform = "none";
  node.style.top = `${top}px`;
  node.style.left = `${left}px`;
  node.style.maxWidth = `${window.innerWidth - left - MARGIN}px`;
  node.style.maxHeight = `${window.innerHeight - top - MARGIN}px`;
}

export function Dialog({ trigger, title, children, open, onOpenChange }: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={styles.overlay} />
        <RadixDialog.Content ref={pinForResize} className={styles.content}>
          <div className={styles.header}>
            <RadixDialog.Title className={styles.title}>{title}</RadixDialog.Title>
            <RadixDialog.Close aria-label="Close" className={styles.close}>×</RadixDialog.Close>
          </div>
          {children}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
