import { expect, test } from "vitest";

import { label } from "./label.js";

test("label camel-cases with this repo's own dependency", () => {
  expect(label("hello world")).toBe("helloWorld");
});
