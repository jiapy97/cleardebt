import { expect, test } from "vitest";

import { deadStatus, formatLabel, sameBranch, selfAssign, withNoise } from "./labels";

test("formatLabel trims", () => {
  expect(formatLabel("  a ")).toBe("a");
});

test("selfAssign returns the value", () => {
  expect(selfAssign(3)).toBe(3);
});

test("sameBranch returns 1", () => {
  expect(sameBranch(true)).toBe(1);
  expect(sameBranch(false)).toBe(1);
});

test("deadStatus labels a closed status", () => {
  expect(deadStatus("closed")).toBe("closed");
  expect(deadStatus("open")).toBe("open");
});

test("withNoise returns the name", () => {
  expect(withNoise("a")).toBe("a");
});
