/**
 * Minimal DOM helpers.
 *
 * Everything here writes through `textContent`; `innerHTML` is never used, so
 * data coming back from Keitaro cannot inject markup into the page.
 */

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = String(value);
    else if (key === "text") node.textContent = String(value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function show(node, visible = true) {
  node.hidden = !visible;
}

export function setBusy(button, busy) {
  button.classList.toggle("is-busy", busy);
  button.disabled = busy;
}

const NUMBER_FORMAT = new Intl.NumberFormat("ru-RU");
const MONEY_FORMAT = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatInt(value) {
  return NUMBER_FORMAT.format(Number(value) || 0);
}

export function formatMoney(value) {
  return MONEY_FORMAT.format(Number(value) || 0);
}

export function formatPercent(value) {
  return `${(Number(value) || 0).toFixed(2)}%`;
}

export function signClass(value) {
  const number = Number(value) || 0;
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "";
}
