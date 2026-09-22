import camelcase from "camelcase";

export function label(name) {
  return camelcase(name);
}
