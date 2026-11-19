/** "Создаватор" кампаний: имя + гео + оффер -> кампания с двумя потоками. */

import { api, ApiError } from "./api.js";
import { Combo } from "./combo.js";
import { clear, el, formatInt, qs, setBusy, show } from "./dom.js";
import { toast } from "./toast.js";

export class CreatorView {
  constructor({ onOpenInEditor }) {
    this.onOpenInEditor = onOpenInEditor;
    this.form = qs("#form-create");
    this.name = qs("#create-name");
    this.geo = qs("#create-geo");
    this.geoHint = qs("#geo-hint");
    this.offerHint = qs("#create-offer-hint");
    this.submit = qs("#create-submit");
    this.result = qs("#create-result");
    this.countries = new Map();
    this.lastCampaignId = null;

    this.offerCombo = new Combo({
      input: qs("#create-offer"),
      list: qs("#create-offer-list"),
      search: (query) => api.offers(query),
      render: (offer) => ({
        title: `[${offer.id}] ${offer.name}`,
        subtitle: offer.url ?? "",
      }),
      onSelect: (offer) => {
        this.offerHint.textContent = offer
          ? `Выбран оффер #${offer.id}`
          : "Оффер не выбран";
      },
    });

    this.form.addEventListener("submit", (event) => this.onSubmit(event));
    this.geo.addEventListener("input", () => this.onGeoInput());
    qs("#create-result-edit").addEventListener("click", () => {
      if (this.lastCampaignId) this.onOpenInEditor(this.lastCampaignId);
    });
  }

  setPrefix(prefix) {
    qs("#prefix-hint").textContent = prefix;
  }

  async load() {
    await Promise.all([this.loadCountries(), this.loadDefaults()]);
  }

  async loadCountries() {
    const countries = await api.countries();
    const datalist = clear(qs("#countries"));
    for (const country of countries) {
      this.countries.set(country.code, country.name);
      datalist.append(el("option", { value: country.code, label: country.name }));
    }
  }

  async loadDefaults() {
    const [defaults, domains, groups, sources] = await Promise.all([
      api.campaignDefaults().catch(() => null),
      api.domains().catch(() => []),
      api.groups().catch(() => []),
      api.sources().catch(() => []),
    ]);

    this.fillSelect(qs("#create-domain"), domains, defaults?.domain_id);
    this.fillSelect(qs("#create-group"), groups, defaults?.group_id);
    this.fillSelect(qs("#create-source"), sources, defaults?.source_id);

    qs("#defaults-preview").textContent = defaults
      ? `По умолчанию: домен ${defaults.domain_name}, группа ${defaults.group_name}, источник ${defaults.source_name}.`
      : "Не удалось получить значения по умолчанию из Keitaro.";
  }

  fillSelect(select, items, selectedId) {
    clear(select);
    for (const item of items) {
      const option = el("option", { value: String(item.id), text: `${item.name} (#${item.id})` });
      if (item.id === selectedId) option.selected = true;
      select.append(option);
    }
    select.disabled = items.length === 0;
  }

  onGeoInput() {
    const code = this.geo.value.trim().toUpperCase();
    if (code.length !== 2) {
      this.geoHint.textContent = "ISO-код страны: AU, MX, RO…";
      return;
    }
    const name = this.countries.get(code);
    this.geoHint.textContent = name ? `Страна: ${name}` : "Неизвестный код страны";
  }

  async onSubmit(event) {
    event.preventDefault();
    const offer = this.offerCombo.value;
    const geo = this.geo.value.trim().toUpperCase();

    if (!this.name.value.trim()) return toast.error("Укажите название кампании.");
    if (!this.countries.has(geo)) return toast.error("Укажите корректный ISO-код страны.");
    if (!offer) return toast.error("Выберите оффер из списка.");

    const payload = {
      name: this.name.value.trim(),
      geo,
      offer_id: offer.id,
      domain_id: numberOrNull(qs("#create-domain").value),
      group_id: numberOrNull(qs("#create-group").value),
      source_id: numberOrNull(qs("#create-source").value),
    };

    setBusy(this.submit, true);
    try {
      const created = await api.createCampaign(payload);
      this.renderResult(created);
      toast.success(`Кампания «${created.campaign.name}» создана.`);
      this.form.reset();
      this.offerCombo.reset();
      this.offerHint.textContent = "Оффер не выбран";
      await this.loadDefaults();
    } catch (error) {
      if (error instanceof ApiError) toast.error(error.message);
      else throw error;
    } finally {
      setBusy(this.submit, false);
    }
  }

  renderResult(created) {
    this.lastCampaignId = created.campaign.id;
    const kv = clear(qs("#create-result-kv"));
    const rows = [
      ["ID кампании", String(created.campaign.id)],
      ["Название", created.campaign.name],
      ["Ссылка", created.tracking_url ?? "—"],
      ["Гео", `${created.geo} — ${created.geo_name}`],
      ["Оффер", `[${created.offer_id}] ${created.offer_name}`],
      ["Домен", created.defaults.domain_name],
      ["Группа", created.defaults.group_name],
      ["Источник", created.defaults.source_name],
    ];
    for (const [label, value] of rows) {
      kv.append(el("dt", { text: label }), el("dd", { text: value }));
    }

    const streams = clear(qs("#create-result-streams"));
    for (const stream of created.streams) {
      streams.append(renderStream(stream));
    }
    show(this.result, true);
  }
}

export function renderStream(stream) {
  const meta = stream.holds_offers
    ? "Офферы кампании"
    : `Редирект → ${stream.redirect_url ?? "—"}`;
  const geo = stream.countries.length ? `Страны: ${stream.countries.join(", ")}` : null;

  return el("li", { class: "stream" }, [
    el("div", { class: "stream__head" }, [
      el("span", { class: "badge badge--pos", text: `#${stream.position ?? "?"}` }),
      el("span", { class: "stream__name", text: stream.name }),
      el("span", {
        class: `badge ${stream.state === "active" ? "badge--active" : ""}`,
        text: stream.state ?? "—",
      }),
    ]),
    el("div", { class: "stream__meta", text: geo ? `${meta} · ${geo}` : meta }),
  ]);
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

export { formatInt };
