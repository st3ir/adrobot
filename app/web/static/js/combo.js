/**
 * Reusable autocomplete combobox.
 *
 * One implementation serves the offer pickers and the campaign picker, so the
 * search/debounce/keyboard logic exists in exactly one place.
 */

import { clear, el, show } from "./dom.js";

const DEBOUNCE_MS = 250;
const MIN_QUERY_FOR_REMOTE = 0;

export class Combo {
  /**
   * @param {object} options
   * @param {HTMLInputElement} options.input
   * @param {HTMLElement} options.list
   * @param {(query: string) => Promise<Array>} options.search
   * @param {(item: object) => {title: string, subtitle?: string}} options.render
   * @param {(item: object|null) => void} options.onSelect
   */
  constructor({ input, list, search, render, onSelect }) {
    this.input = input;
    this.list = list;
    this.search = search;
    this.render = render;
    this.onSelect = onSelect;
    this.items = [];
    this.activeIndex = -1;
    this.selected = null;
    this.timer = null;
    this.requestId = 0;

    this.input.addEventListener("input", () => this.onInput());
    this.input.addEventListener("focus", () => this.onInput());
    this.input.addEventListener("keydown", (event) => this.onKeyDown(event));
    document.addEventListener("click", (event) => {
      if (!this.list.contains(event.target) && event.target !== this.input) this.close();
    });
  }

  get value() {
    return this.selected;
  }

  reset() {
    this.input.value = "";
    this.setSelected(null);
    this.close();
  }

  setSelected(item) {
    this.selected = item;
    this.onSelect?.(item);
  }

  onInput() {
    if (this.selected) this.setSelected(null);
    clearTimeout(this.timer);
    const query = this.input.value.trim();
    if (query.length < MIN_QUERY_FOR_REMOTE) {
      this.close();
      return;
    }
    this.timer = setTimeout(() => this.load(query), DEBOUNCE_MS);
  }

  async load(query) {
    const current = ++this.requestId;
    this.drawMessage("Поиск…");
    let items = [];
    try {
      items = await this.search(query);
    } catch {
      items = [];
    }
    if (current !== this.requestId) return; // a newer search already answered
    this.items = items;
    this.activeIndex = -1;
    this.draw();
  }

  drawMessage(text) {
    clear(this.list);
    this.list.append(el("li", { class: "combo__empty", text }));
    this.open();
  }

  draw() {
    clear(this.list);
    if (!this.items.length) {
      this.list.append(el("li", { class: "combo__empty", text: "Ничего не найдено" }));
    } else {
      this.items.forEach((item, index) => {
        const { title, subtitle } = this.render(item);
        const option = el("li", { class: "combo__option", role: "option" }, [
          el("strong", { text: title }),
          subtitle ? el("span", { text: subtitle }) : null,
        ]);
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          this.choose(index);
        });
        this.list.append(option);
      });
    }
    this.open();
  }

  choose(index) {
    const item = this.items[index];
    if (!item) return;
    this.setSelected(item);
    this.input.value = this.render(item).title;
    this.close();
  }

  onKeyDown(event) {
    if (event.key === "Escape") {
      this.close();
      return;
    }
    if (this.list.hidden || !this.items.length) return;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      this.activeIndex = (this.activeIndex + delta + this.items.length) % this.items.length;
      this.highlight();
    } else if (event.key === "Enter" && this.activeIndex >= 0) {
      event.preventDefault();
      this.choose(this.activeIndex);
    }
  }

  highlight() {
    [...this.list.children].forEach((node, index) => {
      node.classList.toggle("is-active", index === this.activeIndex);
    });
    this.list.children[this.activeIndex]?.scrollIntoView({ block: "nearest" });
  }

  open() {
    show(this.list, true);
    this.input.setAttribute("aria-expanded", "true");
  }

  close() {
    show(this.list, false);
    this.input.setAttribute("aria-expanded", "false");
    this.activeIndex = -1;
  }
}
