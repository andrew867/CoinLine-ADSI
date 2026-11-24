import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const settings = Object.fromEntries(readFileSync("../.env", "utf8").trimEnd().split(/\r?\n/).map((line) => {
  const separator = line.indexOf("=");
  return [line.slice(0, separator), line.slice(separator + 1)];
}));

test.use({ channel: process.env.ADSI_BROWSER_CHANNEL });

test("author and simulate an InfoLine application", async ({ page }) => {
  await page.goto(`http://127.0.0.1:${process.env.ADSI_WEB_PORT || settings.ADSI_WEB_PORT || "8080"}`);
  await page.getByLabel("Console access code").fill(process.env.ADSI_ADMIN_PASSWORD || settings.ADSI_ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Run draft" })).toBeEnabled();

  const name = `Browser verification ${randomUUID().slice(0, 8)}`;
  await page.getByLabel("Import graph").setInputFiles({
    name: name + ".json",
    mimeType: "application/json",
    buffer: readFileSync("../fixtures/apps/weather.graph.json"),
  });
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.getByLabel("Display lines").fill("LOCAL INFOLINE\n1 Weather\n0 Exit");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("saved");
  await expect(page.getByLabel("Display lines")).toHaveValue("LOCAL INFOLINE\n1 Weather\n0 Exit");

  await page.getByRole("button", { name: "Run draft" }).click();
  await expect(page.getByLabel("Terminal display")).toContainText("LOCAL INFOLINE");
  await page.getByRole("button", { name: "Wx", exact: true }).click();
  await expect(page.getByLabel("Terminal display")).toContainText("DEMO WEATHER");
  await expect(page.getByLabel("Terminal display")).toContainText("Demo Harbour");
  const simulator = page.getByRole("complementary").filter({
    has: page.getByRole("heading", { name: "Handset simulator" }),
  });
  await simulator.getByRole("button", { name: "Hang up", exact: true }).click();
  await expect(page.getByLabel("Terminal display")).toContainText("CALL ENDED");

  await page.getByText("Revisions and application settings").click();
  await page.getByRole("button", { name: "Archive and disable routes" }).click();
  await expect(page.getByRole("button", { name: name + " (archived)", exact: true })).toBeVisible();
});
