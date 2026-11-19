/**
 * Редактор кампании.
 *
 * Работает по модели «черновик → публикация»: потоки забираются из Keitaro в
 * нашу базу (Fetch streams), правки живут локально и помечают поток жёлтым, и
 * только Push to Keitaro заливает их в трекер. Cancel откатывает черновик,
 * удалённый оффер остаётся серым в архиве с кнопкой Bring back.
 */

import { api, ApiError } from "./api.js";
import { Combo } from "./combo.js";
import {
  clear,
  el,
  formatInt,
  formatMoney,
  formatPercent,
  qs,
  setBusy,
  show,
  signClass,
} from "./dom.js";
import { toast } from "./toast.js";

export class EditorView {
  constructor() {
    this.campaignId = null;
    this.draft = null;
    this.period = qs("#edit-period");
    this.fetchBtn = qs("#fetch-streams");
    this.addBtn = qs("#add-offer-btn");
    this.addRow = qs("#add-offer-row");

    this.campaignCombo = new Combo({
      input: qs("#edit-campaign"),
      list: qs("#edit-campaign-list"),
      search: (query) => api.listCampaigns(query),
      render: (campaign) => ({
        title: `[${campaign.id}] ${campaign.name}`,
        subtitle: campaign.state ?? "",
      }),
      onSelect: (campaign) => {
        if (campaign) this.open(campaign.id);
      },
    });

    this.addCombo = new Combo({
      input: qs("#add-offer"),
      list: qs("#add-offer-list"),
      search: (query) => api.offers(query),
      render: (offer) => ({ title: `[${offer.id}] ${offer.name}`, subtitle: offer.url ?? "" }),
      onSelect: (offer) => {
        this.addBtn.disabled = !offer || !this.campaignId;
      },
    });

    this.fetchBtn.addEventListener("click", () => this.fetch());
    qs("#fetch-first").addEventListener("click", () => this.fetch());
    this.period.addEventListener("change", () => this.reload());
    this.addBtn.addEventListener("click", () => this.addOffer());
    qs("#publish").addEventListener("click", () => this.publish());
    qs("#discard").addEventListener("click", () => this.discard());
  }

  get days() {
    return Number(this.period.value) || 30;
  }

  async openFromOutside(campaignId) {
    this.campaignCombo.input.value = `[${campaignId}]`;
    await this.open(campaignId);
  }

  async open(campaignId) {
    this.campaignId = campaignId;
    this.fetchBtn.disabled = false;
    await this.reload();
  }

  /** Загружает локальный черновик; 404 означает «ещё не забирали из Keitaro». */
  async reload() {
    if (!this.campaignId) return;
    try {
      this.render(await api.draft(this.campaignId, this.days));
    } catch (error) {
      if (error instanceof ApiError && error.code === "campaign_not_tracked") {
        this.showUntracked();
        return;
      }
      this.fail(error);
    }
  }

  async fetch() {
    if (!this.campaignId) return;
    await this.run(this.fetchBtn, async () => {
      this.render(await api.fetchCampaign(this.campaignId, this.days));
      toast.success("Потоки загружены из Keitaro.");
    });
  }

  async addOffer() {
    const offer = this.addCombo.value;
    if (!offer || !this.campaignId) return;
    await this.run(this.addBtn, async () => {
      this.render(await api.addOffer(this.campaignId, offer.id, this.days));
      toast.success(`Оффер «${offer.name}» добавлен в черновик.`);
      this.addCombo.reset();
    });
    this.addBtn.disabled = true;
  }

  async publish() {
    await this.run(qs("#publish"), async () => {
      this.render(await api.publishDraft(this.campaignId, this.days));
      toast.success("Изменения отправлены в Keitaro.");
    });
  }

  async discard() {
    await this.run(qs("#discard"), async () => {
      this.render(await api.discardDraft(this.campaignId, this.days));
      toast.success("Черновик отменён.");
    });
  }

  async run(button, action) {
    setBusy(button, true);
    try {
      await action();
    } catch (error) {
      this.fail(error);
    } finally {
      setBusy(button, false);
    }
  }

  fail(error) {
    if (error instanceof ApiError) toast.error(error.message);
    else throw error;
  }

  showUntracked() {
    this.draft = null;
    show(qs("#edit-empty"), false);
    show(qs("#edit-body"), false);
    show(this.addRow, false);
    show(qs("#edit-untracked"), true);
  }

  // ---------------------------------------------------------------- render
  render(draft) {
    this.draft = draft;
    show(qs("#edit-empty"), false);
    show(qs("#edit-untracked"), false);
    show(qs("#edit-body"), true);

    qs("#edit-campaign-name").textContent = draft.name;
    const state = qs("#edit-campaign-state");
    state.textContent = draft.is_dirty ? "не опубликовано" : "синхронизировано";
    state.className = `badge ${draft.is_dirty ? "badge--draft" : "badge--active"}`;

    const kv = clear(qs("#edit-campaign-kv"));
    for (const [label, value] of [
      ["ID", String(draft.campaign_id)],
      ["Alias", draft.alias ?? "—"],
      ["Период", `${draft.period.date_from} — ${draft.period.date_to}`],
      ["Загружено", formatMoment(draft.last_synced_at)],
    ]) {
      kv.append(el("dt", { text: label }), el("dd", { text: value }));
    }

    this.renderTotals(draft.totals);
    show(qs("#stats-warning"), !draft.stats_available);
    show(qs("#draft-bar"), draft.is_dirty);

    const host = clear(qs("#streams"));
    for (const stream of draft.streams) host.append(this.renderStream(stream));
    this.placeAddRow();
  }

  /** Форму добавления переносим в карточку потока с офферами. */
  placeAddRow() {
    const slot = qs('#streams [data-add-slot="1"]');
    show(this.addRow, Boolean(slot));
    if (slot) slot.append(this.addRow);
    this.addBtn.disabled = !this.addCombo.value;
  }

  renderTotals(totals) {
    const host = clear(qs("#edit-totals"));
    const tiles = [
      ["Клики", formatInt(totals.clicks)],
      ["Уникальные", formatInt(totals.unique_clicks)],
      ["Конверсии", formatInt(totals.conversions)],
      ["CR", formatPercent(totals.cr)],
      ["Доход", formatMoney(totals.revenue)],
      ["Расход", formatMoney(totals.cost)],
      ["Профит", formatMoney(totals.profit), signClass(totals.profit)],
      ["ROI", formatPercent(totals.roi), signClass(totals.roi)],
    ];
    for (const [label, value, tone] of tiles) {
      host.append(
        el("div", { class: "total" }, [
          el("div", { class: "total__label", text: label }),
          el("div", { class: `total__value ${tone ?? ""}`.trim(), text: value }),
        ]),
      );
    }
  }

  renderStream(stream) {
    const card = el("div", {
      class: `card stream-card${stream.is_dirty ? " is-dirty" : ""}`,
    });

    card.append(
      el("div", { class: "stream-card__head" }, [
        el("span", { class: "badge badge--pos", text: `#${stream.position}` }),
        el("span", { class: "stream__name", text: stream.name }),
        el("span", { class: "badge", text: stream.schema_name ?? "—" }),
        stream.is_dirty ? el("span", { class: "badge badge--draft", text: "не опубликовано" }) : null,
      ]),
    );

    if (!stream.holds_offers) {
      const parts = [];
      if (stream.redirect_url) parts.push(`Редирект → ${stream.redirect_url}`);
      if (stream.countries.length) parts.push(`Страны: ${stream.countries.join(", ")}`);
      card.append(
        el("p", { class: "stream-card__meta", text: parts.join(" · ") || "Без офферов" }),
      );
      return card;
    }

    const active = stream.offers.filter((offer) => offer.state === "active");
    card.append(
      el("p", {
        class: "stream-card__meta",
        text: `Офферов в ротации: ${active.length}, сумма долей ${active.reduce(
          (sum, offer) => sum + offer.share,
          0,
        )}%`,
      }),
      el("div", { dataset: { addSlot: "1" } }),
    );

    if (!stream.offers.length) {
      card.append(el("p", { class: "muted", text: "В потоке пока нет офферов." }));
      return card;
    }

    const body = el("tbody");
    for (const offer of stream.offers) body.append(this.renderOfferRow(offer));
    card.append(
      el("div", { class: "table-wrap" }, [
        el("table", { class: "table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Оффер" }),
              el("th", { class: "num", text: "Доля" }),
              el("th", { class: "num", text: "Клики" }),
              el("th", { class: "num", text: "Уник." }),
              el("th", { class: "num", text: "Конверсии" }),
              el("th", { class: "num", text: "CR" }),
              el("th", { class: "num", text: "Доход" }),
              el("th", { class: "num", text: "Профит" }),
              el("th", { class: "num", text: "ROI" }),
              el("th", {}),
            ]),
          ]),
          body,
        ]),
      ]),
    );
    return card;
  }

  renderOfferRow(offer) {
    const removed = offer.state === "removed";
    const classes = ["", removed ? "is-removed" : "", offer.is_dirty ? "is-dirty" : ""]
      .join(" ")
      .trim();

    const shareInput = el("input", {
      type: "number",
      class: "share-input",
      min: "0",
      max: "100",
      value: String(offer.share),
      disabled: removed,
      title: "Изменить долю — значение закрепится и перестанет пересчитываться",
      "aria-label": `Доля оффера ${offer.name}`,
    });
    shareInput.addEventListener("change", () =>
      this.pin(offer.offer_id, true, clampShare(shareInput.value)),
    );

    const pinBtn = el("button", {
      class: `pin${offer.pinned ? " is-on" : ""}`,
      type: "button",
      text: offer.pinned ? "📌" : "📍",
      disabled: removed,
      title: offer.pinned ? "Доля закреплена — снять" : "Закрепить долю",
    });
    pinBtn.addEventListener("click", () => this.pin(offer.offer_id, !offer.pinned, offer.share));

    const action = el("button", {
      class: removed ? "btn btn--icon-positive" : "btn btn--icon",
      type: "button",
      text: removed ? "Bring back" : "Remove",
    });
    action.addEventListener("click", () => this.toggleOffer(offer, action));

    const m = offer.metrics;
    return el("tr", { class: classes || null }, [
      el("td", { class: "offer-name" }, [
        el("div", { text: `[${offer.offer_id}] ${offer.name}` }),
        offer.url ? el("small", { text: offer.url }) : null,
      ]),
      el("td", { class: "num" }, [
        el("span", { class: "share-cell" }, [shareInput, pinBtn]),
      ]),
      el("td", { class: "num", text: formatInt(m.clicks) }),
      el("td", { class: "num", text: formatInt(m.unique_clicks) }),
      el("td", { class: "num", text: formatInt(m.conversions) }),
      el("td", { class: "num", text: formatPercent(m.cr) }),
      el("td", { class: "num", text: formatMoney(m.revenue) }),
      el("td", { class: `num ${signClass(m.profit)}`.trim(), text: formatMoney(m.profit) }),
      el("td", { class: `num ${signClass(m.roi)}`.trim(), text: formatPercent(m.roi) }),
      el("td", { class: "num" }, [action]),
    ]);
  }

  async toggleOffer(offer, button) {
    const removed = offer.state === "removed";
    await this.run(button, async () => {
      const draft = removed
        ? await api.restoreOffer(this.campaignId, offer.offer_id, this.days)
        : await api.removeOffer(this.campaignId, offer.offer_id, this.days);
      this.render(draft);
    });
  }

  async pin(offerId, pinned, share) {
    try {
      this.render(await api.pinOffer(this.campaignId, offerId, pinned, share, this.days));
    } catch (error) {
      this.fail(error);
      await this.reload();
    }
  }
}

function clampShare(value) {
  const number = Math.round(Number(value));
  if (!Number.isFinite(number)) return 0;
  return Math.min(100, Math.max(0, number));
}

function formatMoment(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ru-RU");
}
