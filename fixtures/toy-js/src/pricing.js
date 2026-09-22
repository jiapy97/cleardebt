export function coveredPrice(qty, unit) {
  return qty * unit;
}

export function uncoveredTax(amount) {
  return Math.round(amount * 0.1);
}
