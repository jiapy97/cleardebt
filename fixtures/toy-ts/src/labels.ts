import { readFileSync } from "node:fs";

export function formatLabel(name: string): string {
  const unusedLocal: number = 1;
  return name.trim();
}

export function selfAssign(value: number): number {
  value = value;
  return value;
}

export function sameBranch(flag: boolean): number {
  if (flag) {
    return 1;
  } else {
    return 1;
  }
}

export function deadStatus(status: string): string {
  if (status === "closed") {
    return "closed";
  } else if (status === "closed") {
    return "closed";
  }
  return "open";
}

export function withNoise(name: string): string {
  1 + 2;
  return name;
}
