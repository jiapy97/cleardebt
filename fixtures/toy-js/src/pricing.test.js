import { expect, test } from "vitest";

import { coveredPrice } from "./pricing.js";

test("coveredPrice multiplies quantity by unit price", () => {
  expect(coveredPrice(2, 5)).toBe(10);
});
