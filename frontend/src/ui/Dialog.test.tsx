import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog } from "./index";

function open() {
  return userEvent.click(screen.getByRole("button", { name: "Expand" }));
}

test("Dialog is closed until the trigger is clicked", async () => {
  render(
    <Dialog trigger={<button>Expand</button>} title="Chart detail">
      <p>body</p>
    </Dialog>,
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await open();
  expect(screen.getByRole("dialog", { name: "Chart detail" })).toBeInTheDocument();
});

test("Dialog closes on Escape", async () => {
  render(
    <Dialog trigger={<button>Expand</button>} title="Chart detail">
      <p>body</p>
    </Dialog>,
  );
  await open();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("an unmeasured dialog is left centred by CSS rather than pinned to 0,0", async () => {
  // jsdom gives every element a 0×0 rect. The resize pin has to notice that and
  // decline, or the dialog would open in the top-left corner in any environment
  // that mounts it before layout.
  render(
    <Dialog trigger={<button>Expand</button>} title="Chart detail">
      <p>body</p>
    </Dialog>,
  );
  await open();
  const dialog = screen.getByRole("dialog", { name: "Chart detail" });
  expect(dialog.style.top).toBe("");
  expect(dialog.style.left).toBe("");
  expect(dialog.style.transform).toBe("");
});
