/** Transient notifications. */

import { el } from "./dom.js";

const HOST_ID = "toasts";
const LIFETIME_MS = 5000;

function host() {
  return document.getElementById(HOST_ID);
}

function push(message, variant) {
  const node = el("div", { class: `toast toast--${variant}`, text: message });
  host().append(node);
  setTimeout(() => node.remove(), LIFETIME_MS);
}

export const toast = {
  success: (message) => push(message, "success"),
  error: (message) => push(message, "error"),
};
