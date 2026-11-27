import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("SwiftParcel investigation journey", () => {
  it("shows an ordinary tracking page before revealing the delivery fee step", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("heading", { name: "Good things are on their way." })).toBeInTheDocument();
    expect(screen.getByLabelText("Your tracking number")).toHaveValue("SP-2048-7721");
    expect(screen.queryByText("€1.99")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /track my parcel/i }));
    expect(screen.getByRole("heading", { name: "Your parcel is almost there." })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /continue to delivery/i }));

    expect(screen.getByRole("heading", { name: "Your parcel is on hold." })).toBeInTheDocument();
    expect(screen.getByText("€1.99")).toBeInTheDocument();
    expect(screen.getByText(/returned to sender/i)).toBeInTheDocument();
  });

  it("keeps mock payment and account fields inert and sends nothing on confirmation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /track my parcel/i }));
    await user.click(screen.getByRole("button", { name: /continue to delivery/i }));

    const sensitiveFields = screen.getAllByRole("textbox").filter((field) => field.getAttribute("placeholder") !== null);
    expect(sensitiveFields.length).toBeGreaterThanOrEqual(4);
    for (const field of sensitiveFields) {
      expect(field).toHaveAttribute("readonly");
      expect(field).not.toHaveAttribute("name");
    }
    const password = document.querySelector<HTMLInputElement>('input[type="password"]');
    expect(password).toHaveAttribute("readonly");
    expect(password).not.toHaveAttribute("name");

    await user.click(screen.getByRole("button", { name: /confirm and pay/i }));
    expect(screen.getByRole("status")).toHaveTextContent("No details were accepted or sent.");
    expect(document.querySelector("form input[placeholder='0000 0000 0000 0000']")).toBeNull();
  });

  it("lets the visitor edit only the tracking code and start from the delivery note", async () => {
    const user = userEvent.setup();
    render(<App />);
    const code = screen.getByLabelText("Your tracking number");
    await user.clear(code);
    await user.type(code, "SP-DEMO-001");
    await user.click(screen.getByRole("button", { name: /review options/i }));
    expect(screen.getByText(/SP-DEMO-001/)).toBeInTheDocument();
  });
});
