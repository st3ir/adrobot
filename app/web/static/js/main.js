/** Application bootstrap: session handling, tabs, view wiring. */

import { api, ApiError, setCsrfToken } from "./api.js";
import { CreatorView } from "./creator.js";
import { EditorView } from "./editor.js";
import { qs, setBusy, show } from "./dom.js";
import { toast } from "./toast.js";

const views = {
  login: qs("#view-login"),
  app: qs("#view-app"),
};

let creator = null;
let editor = null;

function showLogin() {
  show(views.app, false);
  show(views.login, true);
  qs("#login-email").focus();
}

async function showApp(session) {
  setCsrfToken(session.csrf_token);
  qs("#user-email").textContent = session.email;
  show(views.login, false);
  show(views.app, true);

  if (!creator) {
    creator = new CreatorView({ onOpenInEditor: (id) => openEditor(id) });
    editor = new EditorView();
  }
  creator.setPrefix(session.campaign_name_prefix);

  try {
    await creator.load();
  } catch (error) {
    if (error instanceof ApiError) toast.error(`Keitaro: ${error.message}`);
    else throw error;
  }
}

async function openEditor(campaignId) {
  selectTab("edit");
  await editor.openFromOutside(campaignId);
}

function selectTab(name) {
  for (const button of document.querySelectorAll(".tab")) {
    const active = button.dataset.tab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  }
  show(qs("#panel-create"), name === "create");
  show(qs("#panel-edit"), name === "edit");
}

function bindTabs() {
  for (const button of document.querySelectorAll(".tab")) {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
  }
}

function bindLogin() {
  const form = qs("#form-login");
  const errorNode = qs("#login-error");
  const submit = qs("#login-submit");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    show(errorNode, false);
    setBusy(submit, true);
    try {
      const session = await api.login(
        qs("#login-email").value.trim(),
        qs("#login-password").value,
      );
      qs("#login-password").value = "";
      await showApp(session);
    } catch (error) {
      if (error instanceof ApiError) {
        errorNode.textContent = error.message;
        show(errorNode, true);
      } else throw error;
    } finally {
      setBusy(submit, false);
    }
  });
}

function bindLogout() {
  qs("#logout").addEventListener("click", async () => {
    try {
      await api.logout();
    } catch {
      /* the cookie is cleared server-side anyway */
    }
    setCsrfToken(null);
    showLogin();
  });
}

async function boot() {
  bindTabs();
  bindLogin();
  bindLogout();
  try {
    await showApp(await api.session());
  } catch (error) {
    if (error instanceof ApiError && error.isUnauthorized) showLogin();
    else {
      showLogin();
      if (error instanceof ApiError) toast.error(error.message);
    }
  }
}

boot();
