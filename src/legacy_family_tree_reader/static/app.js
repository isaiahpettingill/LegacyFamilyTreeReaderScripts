"use strict";

const elements = {
  appStatus: document.querySelector("#app-status"),
  sourceMode: document.querySelector("#source-mode"),
  databaseFile: document.querySelector("#database-file"),
  dataset: document.querySelector("#dataset-select"),
  searchForm: document.querySelector("#search-form"),
  searchInput: document.querySelector("#search-input"),
  searchButton: document.querySelector("#search-form button"),
  searchState: document.querySelector("#search-state"),
  searchResults: document.querySelector("#search-results"),
  browseControls: document.querySelector("#browse-controls"),
  browseAll: document.querySelector("#browse-all"),
  browsePrevious: document.querySelector("#browse-previous"),
  browseNext: document.querySelector("#browse-next"),
  browseCount: document.querySelector("#browse-count"),
  recordEmpty: document.querySelector("#record-empty"),
  recordContent: document.querySelector("#record-content"),
  recordState: document.querySelector("#record-state"),
  personKicker: document.querySelector("#person-kicker"),
  personName: document.querySelector("#person-name"),
  personLifespan: document.querySelector("#person-lifespan"),
  overview: document.querySelector("#person-overview"),
  facts: document.querySelector("#facts-content"),
  family: document.querySelector("#family-content"),
  setPersonA: document.querySelector("#set-person-a"),
  setPersonB: document.querySelector("#set-person-b"),
  treeForm: document.querySelector("#tree-form"),
  generations: document.querySelector("#generations-select"),
  treeState: document.querySelector("#tree-state"),
  tree: document.querySelector("#tree-content"),
  treeZoomOut: document.querySelector("#tree-zoom-out"),
  treeZoomIn: document.querySelector("#tree-zoom-in"),
  treeZoomReset: document.querySelector("#tree-zoom-reset"),
  treeZoomLevel: document.querySelector("#tree-zoom-level"),
  skipLink: document.querySelector("#skip-link"),
  peopleTab: document.querySelector("#people-tab"),
  fullTreeTab: document.querySelector("#full-tree-tab"),
  peoplePanel: document.querySelector("#people-panel"),
  fullTreePanel: document.querySelector("#full-tree-panel"),
  fullTreeSummary: document.querySelector(".full-tree-summary"),
  fullTreeState: document.querySelector("#full-tree-state"),
  fullTree: document.querySelector("#full-tree-content"),
  fullTreeBreadcrumbs: document.querySelector("#full-tree-breadcrumbs"),
  fullTreeReset: document.querySelector("#full-tree-reset"),
  fullTreeOlder: document.querySelector("#full-tree-older"),
  fullTreeNewer: document.querySelector("#full-tree-newer"),
  fullTreeGenerations: document.querySelector("#full-tree-generations"),
  fullTreeZoomOut: document.querySelector("#full-tree-zoom-out"),
  fullTreeZoomIn: document.querySelector("#full-tree-zoom-in"),
  fullTreeZoomReset: document.querySelector("#full-tree-zoom-reset"),
  fullTreeZoomLevel: document.querySelector("#full-tree-zoom-level"),
  personACard: document.querySelector("#person-a-card"),
  personBCard: document.querySelector("#person-b-card"),
  relationshipButton: document.querySelector("#find-relationship"),
  relationshipState: document.querySelector("#relationship-state"),
  relationshipResult: document.querySelector("#relationship-result")
};

const BROWSE_PAGE_SIZE = 100;
const FULL_TREE_DATASET_ID = "1";
const FULL_TREE_ROOT_IDS = ["1", "2"];
const FULL_TREE_MIN_GENERATIONS = 1;
const FULL_TREE_MAX_GENERATIONS = 6;
const FULL_TREE_DEFAULT_GENERATIONS = 1;
const FULL_TREE_ROOT_LABEL = "Douglas & Martha Patten";
const FULL_TREE_COUPLE_WIDTH = 250;
const FULL_TREE_COLUMN_GAP = 170;
const FULL_TREE_ROW_HEIGHT = 200;
const FULL_TREE_PAD_X = 48;
const FULL_TREE_PAD_Y = 56;
const ROUTE_ID_PATTERN = /^[^\u0000-\u001f\u007f]{1,256}$/;

const state = {
  transport: null,
  sourceVersion: 0,
  startupController: null,
  datasetId: "",
  datasetsReady: false,
  catalogMode: "browse",
  catalogBusy: false,
  catalogRequestId: 0,
  browseOffset: 0,
  browsePeople: [],
  browseTotal: 0,
  browseHasMore: false,
  currentPerson: null,
  personA: null,
  personB: null,
  searchTimer: null,
  catalogController: null,
  recordController: null,
  treeController: null,
  relationshipController: null,
  routeVersion: 0,
  treeScale: 1,
  treeMap: null,
  treeSurface: null,
  treeCards: null,
  treeGraphs: [],
  treeRootId: "",
  lastPeopleRoute: { kind: "root" },
  fullTreeController: null,
  fullTreeLoadKey: "",
  fullTreeTransform: { x: 0, y: 0, scale: 1 },
  fullTreeMap: null,
  fullTreeGraph: null,
  fullTreeLayout: null,
  fullTreeCoupleCards: new Map(),
  fullTreePeople: new Map(),
  fullTreeRoots: [],
  fullTreeHasParents: new Set(),
  fullTreeFocus: { firstId: FULL_TREE_ROOT_IDS[0], secondId: FULL_TREE_ROOT_IDS[1] },
  fullTreeFocusStack: [],
  fullTreeFocusLabel: FULL_TREE_ROOT_LABEL,
  fullTreeGenerations: FULL_TREE_DEFAULT_GENERATIONS,
  fullTreeRootLabel: FULL_TREE_ROOT_LABEL
};
let standaloneLoader = null;

function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  if (options.type) node.type = options.type;
  if (options.dataset) {
    Object.entries(options.dataset).forEach(([key, value]) => {
      node.dataset[key] = String(value);
    });
  }
  const childList = Array.isArray(children) ? children : [children];
  childList.filter(Boolean).forEach((child) => node.append(child));
  return node;
}

function setMessage(target, message = "", kind = "") {
  target.textContent = message;
  if (kind) target.dataset.kind = kind;
  else delete target.dataset.kind;
}

function firstValue(object, keys) {
  if (!object || typeof object !== "object") return undefined;
  for (const key of keys) {
    const value = object[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function listFrom(payload, keys) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of keys) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

function personId(person) {
  const value = firstValue(person, ["person_id", "id", "individual_id", "IndividualID", "MRIN"]);
  return value === undefined ? "" : String(value);
}

function personName(person) {
  if (!person) return "Unknown person";
  if (typeof person === "string") return person || "Unknown person";
  const direct = firstValue(person, ["display_name", "full_name", "name", "preferred_name", "Name"]);
  if (direct) return String(direct);
  const given = firstValue(person, ["given_names", "given_name", "first_name", "given", "GivenName", "FirstName"]);
  const surname = firstValue(person, ["surname", "last_name", "family_name", "Surname", "LastName"]);
  const suffix = firstValue(person, ["suffix", "name_suffix"]);
  const assembled = [given, surname, suffix].filter(Boolean).join(" ");
  return assembled || `Person ${personId(person) || "unknown"}`;
}

function displayValue(value) {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(displayValue).filter(Boolean).join(", ");
  if (typeof value === "object") {
    return String(firstValue(value, [
      "display", "display_name", "formatted", "text", "value", "name", "title",
      "event_type_name", "location_name", "place_name", "legacy_date", "date", "place"
    ]) || "");
  }
  return String(value);
}

function legacyDateDisplay(value) {
  const text = displayValue(value).trim();
  if (!text || ["0", "-99999999", "99999999"].includes(text)) return "";
  const packed = /^(\d{2})(\d{2})(\d{2})(\d{4})(\d{8})$/.exec(text);
  if (packed && packed[5] === "00000000" && ["00", "10"].includes(packed[1])) {
    const year = packed[4];
    const month = Number(packed[3]);
    const day = Number(packed[2]);
    let formatted = year;
    if (month >= 1 && month <= 12) {
      formatted += `-${String(month).padStart(2, "0")}`;
      if (day >= 1 && day <= new Date(Number(year), month, 0).getDate()) {
        formatted += `-${String(day).padStart(2, "0")}`;
      }
    }
    return packed[1] === "10" ? `about ${formatted}` : formatted;
  }
  const sortable = /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (sortable) {
    const month = Number(sortable[2]);
    const day = Number(sortable[3]);
    if (month === 0 && day === 0) return sortable[1];
    if (month >= 1 && month <= 12 && day === 0) return `${sortable[1]}-${sortable[2]}`;
    if (month >= 1 && month <= 12 && day >= 1 && day <= new Date(Number(sortable[1]), month, 0).getDate()) {
      return `${sortable[1]}-${sortable[2]}-${sortable[3]}`;
    }
  }
  return text;
}

function sexDisplay(value) {
  const code = displayValue(value).trim().toLowerCase();
  if (["0", "m", "male"].includes(code)) return "M";
  if (["1", "f", "female"].includes(code)) return "F";
  if (["2", "u", "unknown", "unspecified"].includes(code)) return "U";
  return code.toUpperCase();
}

function lifeSummary(person) {
  if (!person || typeof person !== "object") return "";
  const direct = firstValue(person, ["lifespan", "life_span", "dates"]);
  if (direct && typeof direct !== "object") return String(direct);
  const birth = legacyDateDisplay(firstValue(person, ["birth_date_display", "birth_legacy_date", "birth_date", "birth", "date_of_birth", "BirthDate"]));
  const death = legacyDateDisplay(firstValue(person, ["death_date_display", "death_legacy_date", "death_date", "death", "date_of_death", "DeathDate"]));
  if (!birth && !death) return "Dates not recorded";
  return `${birth || "?"}–${death || ""}`;
}

function datasetId(dataset) {
  const id = firstValue(dataset, ["dataset_id", "id", "slug", "key"]);
  return id === undefined ? "" : String(id);
}

function datasetName(dataset) {
  if (typeof dataset === "string") return dataset;
  return String(firstValue(dataset, ["name", "display_name", "label", "source_file_name", "filename", "dataset_id", "id"]) || "Unnamed collection");
}

function validRouteId(value) {
  return typeof value === "string" && ROUTE_ID_PATTERN.test(value) && value !== "." && value !== "..";
}

function decodeRouteId(value) {
  try {
    const decoded = decodeURIComponent(value);
    return validRouteId(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

function parseRoute() {
  const raw = window.location.protocol === "file:"
    ? window.location.hash.replace(/^#/, "")
    : window.location.pathname;
  if (!raw || raw === "/" || (window.location.protocol !== "file:" && /\/index\.html\/?$/.test(raw))) {
    return { kind: "root" };
  }
  if (/^\/full-tree\/?$/.test(raw)) return { kind: "full-tree" };
  const match = /^\/dataset\/([^/]+)\/person\/([^/]+)\/?$/.exec(raw);
  if (!match) return { kind: "invalid", message: "The archive link is not a recognized person route." };
  const routeDatasetId = decodeRouteId(match[1]);
  const routePersonId = decodeRouteId(match[2]);
  if (!routeDatasetId || !routePersonId) {
    return { kind: "invalid", message: "The archive link contains an invalid dataset or person identifier." };
  }
  return { kind: "person", datasetId: routeDatasetId, personId: routePersonId };
}

function routeText(route) {
  if (route.kind === "full-tree") return "/full-tree";
  if (route.kind !== "person") return "/";
  return `/dataset/${encodeURIComponent(route.datasetId)}/person/${encodeURIComponent(route.personId)}`;
}

function writeRoute(route, replace = false) {
  const path = routeText(route);
  const target = window.location.protocol === "file:"
    ? `${window.location.pathname}${window.location.search}#${path}`
    : path;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (current === target) return false;
  window.history[replace ? "replaceState" : "pushState"](null, "", target);
  return true;
}

function clearSelectedPerson() {
  state.routeVersion += 1;
  state.currentPerson = null;
  state.recordController?.abort();
  state.treeController?.abort();
  elements.recordContent.hidden = true;
  elements.recordEmpty.hidden = false;
  elements.tree.replaceChildren();
  setMessage(elements.recordState);
  setMessage(elements.treeState);
}

async function applyRoute(summary = null) {
  if (!state.datasetsReady) return;
  const route = parseRoute();
  if (route.kind === "invalid") {
    showTopLevelView("people");
    clearSelectedPerson();
    setMessage(elements.appStatus, `${route.message} Return to the archive root and choose a person.`, "error");
    return;
  }
  if (route.kind === "full-tree") {
    state.routeVersion += 1;
    state.recordController?.abort();
    state.treeController?.abort();
    showTopLevelView("full-tree");
    writeRoute(route, true);
    setMessage(elements.appStatus, "");
    loadFullTree();
    return;
  }
  showTopLevelView("people");
  state.lastPeopleRoute = route;
  if (route.kind === "root") {
    setMessage(elements.appStatus, "");
    clearSelectedPerson();
    return;
  }
  const matchingOption = Array.from(elements.dataset.options)
    .find((option) => option.value === route.datasetId);
  if (!matchingOption) {
    clearSelectedPerson();
    setMessage(elements.appStatus, `Dataset "${route.datasetId}" from this link is not available.`, "error");
    return;
  }
  writeRoute(route, true);
  setMessage(elements.appStatus, "");
  if (state.datasetId !== route.datasetId) {
    elements.dataset.value = route.datasetId;
    resetForDataset();
    await loadBrowsePage(0);
    if (parseRoute().kind !== "person" || parseRoute().datasetId !== route.datasetId) return;
  }
  const hint = summary && personId(summary) === route.personId ? summary : { person_id: route.personId };
  await loadPerson(hint, route);
}

function openPerson(summary) {
  const id = personId(summary);
  if (!validRouteId(id) || !validRouteId(state.datasetId)) {
    setMessage(elements.searchState, "This person has an invalid identifier and cannot be opened.", "error");
    return;
  }
  const route = { kind: "person", datasetId: state.datasetId, personId: id };
  const current = parseRoute();
  if (current.kind === "person" && current.datasetId === route.datasetId && current.personId === id) {
    loadPerson(summary, route);
    return;
  }
  writeRoute(route);
  applyRoute(summary);
}

function showTopLevelView(view) {
  const fullTree = view === "full-tree";
  elements.peoplePanel.hidden = fullTree;
  elements.fullTreePanel.hidden = !fullTree;
  elements.peopleTab.setAttribute("aria-selected", String(!fullTree));
  elements.fullTreeTab.setAttribute("aria-selected", String(fullTree));
  elements.peopleTab.tabIndex = fullTree ? -1 : 0;
  elements.fullTreeTab.tabIndex = fullTree ? 0 : -1;
  elements.skipLink.href = fullTree ? "#full-tree-panel" : "#main-content";
  elements.skipLink.textContent = fullTree ? "Skip to full family tree" : "Skip to family records";
}

class ApiRequestError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

class ApiFormatError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiFormatError";
  }
}

function abortError() {
  return new DOMException("The request was cancelled", "AbortError");
}

function redirectToLogin(response, requestedUrl) {
  const finalUrl = response.url || "";
  if (response.redirected && finalUrl && finalUrl !== new URL(requestedUrl, window.location.href).href) {
    window.location.assign(finalUrl);
  } else {
    window.location.reload();
  }
  throw abortError();
}

async function fetchJson(path, controller) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal: controller?.signal
  });
  if (response.status === 401) redirectToLogin(response, path);
  if (response.redirected && !response.headers.get("Content-Type")?.includes("application/json")) {
    redirectToLogin(response, path);
  }
  let data = null;
  let parsed = false;
  try {
    data = await response.json();
    parsed = true;
  } catch {
    // A proxy error page may not contain JSON.
  }
  if (!response.ok) {
    const detail = firstValue(data, ["detail", "message", "error"]);
    throw new ApiRequestError(
      response.status,
      detail ? displayValue(detail) : `Request failed (${response.status})`
    );
  }
  if (!parsed) throw new ApiFormatError("The server returned an unexpected response.");
  return data;
}

async function api(path, controller) {
  if (state.transport === "standalone") {
    if (controller?.signal.aborted) throw abortError();
    const data = await window.LegacyStandalone.request(path);
    if (controller?.signal.aborted) throw abortError();
    return data;
  }
  if (state.transport === "server") return fetchJson(path, controller);
  throw new Error("Choose a SQLite database to open the archive.");
}

function networkHelp() {
  if (window.location.protocol === "file:") {
    return "Choose a database with Open SQLite file.";
  }
  return "Could not connect to the archive. Keep `legacy-family-tree browse ...` running in a terminal, then reload this page.";
}

function errorMessage(error) {
  if (error?.name === "AbortError") return "";
  if (error instanceof TypeError) return networkHelp();
  if (error instanceof Error && error.message) return error.message.split(/\r?\n/, 1)[0];
  return "The archive could not complete this request.";
}

function setSourceMode(mode) {
  const labels = {
    server: "Source: Archive server",
    direct: "Source: Direct SQLite file"
  };
  elements.sourceMode.textContent = labels[mode] || "Source: Checking archive...";
}

function updateCatalogControls() {
  const ready = state.datasetsReady && Boolean(state.datasetId);
  const busy = state.catalogBusy;
  elements.dataset.disabled = !ready || busy;
  // Disabling a focused input makes browsers blur it during every live search.
  elements.searchInput.disabled = !ready;
  elements.searchButton.disabled = !ready || busy;
  elements.browseControls.hidden = !ready;
  elements.browseAll.disabled = !ready || busy;
  const browsing = ready && state.catalogMode === "browse";
  elements.browsePrevious.disabled = !browsing || busy || state.browseOffset === 0;
  elements.browseNext.disabled = !browsing || busy || !state.browseHasMore;
  elements.searchResults.querySelectorAll("button").forEach((button) => {
    button.disabled = !ready || busy;
  });
  elements.searchResults.setAttribute("aria-busy", String(busy));
}

async function loadDatasets(payload) {
  let datasets = listFrom(payload, ["datasets", "items", "results"]);
  if (!datasets.length && payload && typeof payload === "object" && datasetId(payload)) datasets = [payload];
  elements.dataset.replaceChildren();
  state.datasetsReady = false;
  state.datasetId = "";
  if (!datasets.length) {
    elements.dataset.append(element("option", { text: "No collections available" }));
    updateCatalogControls();
    setMessage(elements.appStatus, "No family record collections are available.", "error");
    return;
  }
  datasets.forEach((dataset) => {
    const option = element("option", { text: datasetName(dataset) });
    option.value = datasetId(dataset) || datasetName(dataset);
    elements.dataset.append(option);
  });
  state.datasetsReady = true;
  const initialRoute = parseRoute();
  if (initialRoute.kind === "person" && Array.from(elements.dataset.options).some((option) => option.value === initialRoute.datasetId)) {
    elements.dataset.value = initialRoute.datasetId;
  }
  state.datasetId = elements.dataset.value;
  resetForDataset();
  setMessage(elements.appStatus, "");
  await loadBrowsePage(0);
  await applyRoute();
}

function resetForDataset() {
  clearTimeout(state.searchTimer);
  state.datasetId = elements.dataset.value;
  state.currentPerson = null;
  state.personA = null;
  state.personB = null;
  state.catalogController?.abort();
  state.catalogRequestId += 1;
  state.recordController?.abort();
  state.treeController?.abort();
  state.relationshipController?.abort();
  state.catalogMode = "browse";
  state.catalogBusy = false;
  state.browseOffset = 0;
  state.browsePeople = [];
  state.browseTotal = 0;
  state.browseHasMore = false;
  elements.searchInput.value = "";
  elements.searchResults.replaceChildren();
  elements.recordContent.hidden = true;
  elements.recordEmpty.hidden = false;
  elements.relationshipResult.replaceChildren();
  elements.browseCount.textContent = "";
  setMessage(elements.searchState, "Loading people...");
  setMessage(elements.recordState);
  setMessage(elements.treeState);
  setMessage(elements.relationshipState);
  updateRelationshipCards();
  updateCatalogControls();
}

async function searchPeople(query) {
  const trimmed = query.trim();
  state.catalogController?.abort();
  elements.searchResults.replaceChildren();
  if (!trimmed) {
    showCurrentBrowsePage();
    return;
  }
  const requestId = ++state.catalogRequestId;
  state.catalogController = new AbortController();
  const controller = state.catalogController;
  state.catalogMode = "search";
  elements.searchResults.setAttribute("aria-label", "Search results");
  state.catalogBusy = true;
  updateCatalogControls();
  setMessage(elements.searchState, "Searching the index...");
  try {
    const params = new URLSearchParams({ dataset_id: state.datasetId, q: trimmed, limit: "50" });
    const payload = await api(`/api/people/search?${params}`, controller);
    if (controller.signal.aborted || requestId !== state.catalogRequestId) return;
    const people = listFrom(payload, ["people", "results", "items", "matches"]);
    renderPeopleResults(people);
    setMessage(elements.searchState, people.length ? `${people.length} ${people.length === 1 ? "person" : "people"} found.` : "No matching people found. Try fewer letters or another spelling.");
  } catch (error) {
    const message = errorMessage(error);
    if (message) setMessage(elements.searchState, `Search failed: ${message}`, "error");
  } finally {
    if (requestId === state.catalogRequestId) {
      state.catalogBusy = false;
      updateCatalogControls();
    }
  }
}

async function loadBrowsePage(offset) {
  state.catalogController?.abort();
  const requestId = ++state.catalogRequestId;
  const datasetAtStart = state.datasetId;
  state.catalogController = new AbortController();
  const controller = state.catalogController;
  state.catalogMode = "browse";
  state.catalogBusy = true;
  elements.searchResults.replaceChildren();
  setMessage(elements.searchState, "Loading people...");
  updateCatalogControls();
  try {
    const params = new URLSearchParams({
      dataset_id: datasetAtStart,
      limit: String(BROWSE_PAGE_SIZE),
      offset: String(Math.max(0, offset))
    });
    const payload = await api(`/api/people?${params}`, controller);
    if (controller.signal.aborted || requestId !== state.catalogRequestId || datasetAtStart !== state.datasetId) return;
    const people = listFrom(payload, ["people", "results", "items"]);
    const payloadOffset = Number(firstValue(payload, ["offset"]));
    const payloadTotal = Number(firstValue(payload, ["total", "count"]));
    state.browseOffset = Number.isFinite(payloadOffset) ? payloadOffset : Math.max(0, offset);
    state.browseTotal = Number.isFinite(payloadTotal) ? payloadTotal : state.browseOffset + people.length;
    state.browseHasMore = typeof payload?.has_more === "boolean"
      ? payload.has_more
      : state.browseOffset + people.length < state.browseTotal;
    state.browsePeople = people;
    showCurrentBrowsePage();
  } catch (error) {
    const message = errorMessage(error);
    if (message) setMessage(elements.searchState, `People could not be loaded: ${message}`, "error");
  } finally {
    if (requestId === state.catalogRequestId) {
      state.catalogBusy = false;
      updateCatalogControls();
    }
  }
}

function showCurrentBrowsePage() {
  state.catalogMode = "browse";
  renderPeopleResults(state.browsePeople);
  elements.searchResults.setAttribute("aria-label", "People in this collection");
  const first = state.browsePeople.length ? state.browseOffset + 1 : 0;
  const last = state.browseOffset + state.browsePeople.length;
  const page = Math.floor(state.browseOffset / BROWSE_PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(state.browseTotal / BROWSE_PAGE_SIZE));
  elements.browseCount.textContent = `Page ${page} of ${pages}; rows ${first}-${last} of ${state.browseTotal}`;
  setMessage(
    elements.searchState,
    state.browsePeople.length ? `Showing rows ${first}-${last} of ${state.browseTotal}.` : "No people are recorded in this collection."
  );
  updateCatalogControls();
}

function renderPeopleResults(people) {
  const fragment = document.createDocumentFragment();
  people.forEach((person) => {
    const openButton = element("button", { className: "result-open", type: "button" }, [
      element("strong", { text: personName(person) }),
      element("span", { text: lifeSummary(person) })
    ]);
    openButton.addEventListener("click", () => openPerson(person));

    const useA = element("button", { className: "mini-button", type: "button", text: "Set as A" });
    const useB = element("button", { className: "mini-button", type: "button", text: "Set as B" });
    useA.addEventListener("click", () => setRelationshipPerson("A", person));
    useB.addEventListener("click", () => setRelationshipPerson("B", person));

    fragment.append(element("li", { className: "search-result" }, [
      openButton,
      element("div", { className: "result-actions" }, [useA, useB])
    ]));
  });
  elements.searchResults.replaceChildren(fragment);
}

function cancelActiveRequests() {
  clearTimeout(state.searchTimer);
  state.catalogController?.abort();
  state.recordController?.abort();
  state.treeController?.abort();
  state.fullTreeController?.abort();
  state.relationshipController?.abort();
  state.catalogRequestId += 1;
  state.catalogBusy = false;
  state.fullTreeLoadKey = "";
}

function loadScript(path) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = path;
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", () => reject(new Error(`Could not load ${path}.`)), { once: true });
    document.head.append(script);
  });
}

async function ensureStandaloneReader() {
  if (window.LegacyStandalone) return;
  if (!standaloneLoader) {
    standaloneLoader = (async () => {
      await loadScript("vendor/sql-asm.js");
      await loadScript("standalone.js");
      if (!window.LegacyStandalone) {
        throw new Error("The in-browser SQLite reader could not be loaded.");
      }
    })();
  }
  await standaloneLoader;
}

async function activateStandalone(file, sourceKind, version, description) {
  let opened = false;
  elements.databaseFile.disabled = true;
  state.catalogBusy = true;
  updateCatalogControls();
  setMessage(elements.appStatus, description);
  try {
    await ensureStandaloneReader();
    await window.LegacyStandalone.open(file);
    opened = true;
    if (version !== state.sourceVersion) return;
    state.transport = "standalone";
    setSourceMode(sourceKind);
    const payload = await window.LegacyStandalone.request("/api/datasets");
    if (version !== state.sourceVersion) return;
    await loadDatasets(payload);
  } catch (error) {
    if (version !== state.sourceVersion || error?.name === "AbortError") return;
    const message = errorMessage(error);
    if (opened || !state.datasetsReady) {
      elements.dataset.replaceChildren(element("option", { text: "Collections unavailable" }));
      state.datasetsReady = false;
    }
    state.catalogBusy = false;
    updateCatalogControls();
    setMessage(elements.appStatus, `Could not open the SQLite database: ${message}`, "error");
  } finally {
    if (version === state.sourceVersion) elements.databaseFile.disabled = false;
  }
}

async function openSelectedFile(file) {
  if (!file) return;
  state.startupController?.abort();
  const version = ++state.sourceVersion;
  cancelActiveRequests();
  await activateStandalone(
    file,
    "direct",
    version,
    `Opening ${file.name || "SQLite database"} read-only in memory...`
  );
}

async function initializeHttp() {
  const version = ++state.sourceVersion;
  const controller = new AbortController();
  state.startupController = controller;
  setMessage(elements.appStatus, "Connecting to the archive server...");
  try {
    const payload = await fetchJson("/api/datasets", controller);
    if (version !== state.sourceVersion) return;
    state.transport = "server";
    setSourceMode("server");
    await loadDatasets(payload);
    return;
  } catch (startupError) {
    if (startupError?.name === "AbortError" || version !== state.sourceVersion) return;
    state.transport = null;
    setSourceMode("");
    elements.dataset.replaceChildren(element("option", { text: "Collections unavailable" }));
    setMessage(elements.appStatus, `Could not open the archive: ${errorMessage(startupError)}`, "error");
  }
}

function initialize() {
  showTopLevelView(parseRoute().kind === "full-tree" ? "full-tree" : "people");
  if (window.location.protocol === "file:") {
    state.transport = "standalone";
    setSourceMode("direct");
    elements.dataset.replaceChildren(element("option", { text: "Choose a SQLite database" }));
    setMessage(elements.appStatus, "Choose a database with Open SQLite file. It will stay read-only in this browser.");
    updateCatalogControls();
    return;
  }
  initializeHttp();
}

async function loadPerson(summary, route) {
  const id = personId(summary);
  if (!id || route.datasetId !== state.datasetId) return;
  const routeVersion = ++state.routeVersion;
  state.recordController?.abort();
  state.treeController?.abort();
  state.recordController = new AbortController();
  state.currentPerson = summary;
  elements.recordEmpty.hidden = true;
  elements.recordContent.hidden = false;
  elements.personName.textContent = personName(summary);
  elements.personLifespan.textContent = lifeSummary(summary);
  elements.personKicker.textContent = `Person record · ${id}`;
  elements.overview.replaceChildren();
  elements.facts.replaceChildren();
  elements.family.replaceChildren();
  elements.tree.replaceChildren();
  setMessage(elements.recordState, "Opening record...");
  setMessage(elements.treeState, "Loading the pedigree navigator...");
  loadTree();

  const base = `/api/people/${encodeURIComponent(state.datasetId)}/${encodeURIComponent(id)}`;
  const signal = state.recordController;
  const requests = await Promise.allSettled([
    api(base, signal),
    api(`${base}/facts`, signal),
    api(`${base}/family`, signal)
  ]);
  if (signal.signal.aborted || routeVersion !== state.routeVersion) return;

  const [personRequest, factsRequest, familyRequest] = requests;
  if (personRequest.status === "fulfilled") {
    const person = unwrapPerson(personRequest.value) || summary;
    state.currentPerson = person;
    elements.personName.textContent = personName(person);
    elements.personLifespan.textContent = lifeSummary(person);
    renderOverview(person);
  } else {
    renderOverview(summary);
  }

  if (factsRequest.status === "fulfilled") renderFacts(factsRequest.value);
  else renderSectionError(elements.facts, "Facts and notes", factsRequest.reason);

  if (familyRequest.status === "fulfilled") renderFamily(familyRequest.value);
  else renderSectionError(elements.family, "Family connections", familyRequest.reason);

  const failures = requests.filter((request) => request.status === "rejected" && request.reason?.name !== "AbortError").length;
  setMessage(elements.recordState, failures ? `${failures} part${failures === 1 ? "" : "s"} of this record could not be loaded.` : "", failures ? "error" : "");
  updateRelationshipCards();
  elements.recordContent.scrollIntoView({ behavior: "smooth", block: "start" });
}

function unwrapPerson(payload) {
  if (!payload || typeof payload !== "object") return null;
  return payload.person || payload.individual || payload.record || payload;
}

function renderOverview(person) {
  const fields = [
    ["Full name", ["display_name", "full_name", "name"]],
    ["Given names", ["given_names", "given_name", "first_name", "given"]],
    ["Surname", ["surname", "last_name", "family_name"]],
    ["Sex", ["gender_code", "sex", "gender"], sexDisplay],
    ["Birth", ["birth_date_display", "birth_legacy_date", "birth_date", "birth", "date_of_birth"], legacyDateDisplay],
    ["Birthplace", ["birth_place", "place_of_birth"]],
    ["Death", ["death_date_display", "death_legacy_date", "death_date", "death", "date_of_death"], legacyDateDisplay],
    ["Death place", ["death_place", "place_of_death"]],
    ["Burial", ["burial_date_display", "burial_date", "burial"], legacyDateDisplay],
    ["Burial place", ["burial_place", "cemetery"]],
    ["Legacy RIN", ["legacy_rin"]],
    ["Record ID", ["person_id", "id", "individual_id"]]
  ];
  const rows = [];
  const seen = new Set();
  fields.forEach(([label, keys, formatter = displayValue]) => {
    const text = formatter(firstValue(person, keys));
    if (!text || seen.has(`${label}:${text}`)) return;
    seen.add(`${label}:${text}`);
    rows.push(element("div", {}, [element("dt", { text: label }), element("dd", { text })]));
  });
  if (!rows.length) rows.push(element("div", {}, [element("dt", { text: "Record" }), element("dd", { text: "No overview details recorded." })]));
  elements.overview.replaceChildren(...rows);
}

function factTitle(fact) {
  return displayValue(firstValue(fact, ["type", "fact_type", "event_type", "event_type_name", "title", "name", "label"])) || "Recorded fact";
}

function noteText(note) {
  if (typeof note === "string" || typeof note === "number") return String(note);
  return displayValue(firstValue(note, ["text", "note", "content", "value", "description", "body"]));
}

function humanize(key) {
  return String(key).replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function collectNotes(payload, facts) {
  const candidates = [];
  const notePayload = payload?.notes || payload?.person_notes;
  if (Array.isArray(notePayload)) candidates.push(...notePayload);
  else if (notePayload && typeof notePayload === "object") {
    Object.entries(notePayload).forEach(([key, value]) => {
      const text = noteText(value);
      if (text) candidates.push(`${humanize(key)}: ${text}`);
    });
  } else if (notePayload) candidates.push(notePayload);
  if (payload?.general_notes && payload.general_notes !== notePayload) candidates.push(payload.general_notes);
  facts.forEach((fact) => {
    if (!fact || typeof fact !== "object") return;
    const notes = listFrom(fact, ["notes", "note"]);
    if (notes.length) candidates.push(...notes);
    else if (fact.note) candidates.push(fact.note);
  });
  const seen = new Set();
  return candidates.map(noteText).filter((text) => {
    if (!text || seen.has(text)) return false;
    seen.add(text);
    return true;
  });
}

function renderFacts(payload) {
  let facts = listFrom(payload, ["facts", "events", "items", "vital_facts"]);
  if (!facts.length && payload && typeof payload === "object") {
    const hasFactShape = firstValue(payload, ["type", "fact_type", "event_type", "date", "place"]);
    if (hasFactShape) facts = [payload];
  }
  const identity = payload?.identity || payload?.person || {};
  const vitalFacts = [
    ["Birth", firstValue(identity, ["birth_date_display", "birth_legacy_date", "birth_date", "date_of_birth"])],
    ["Death", firstValue(identity, ["death_date_display", "death_legacy_date", "death_date", "date_of_death"])]
  ].filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([type, date]) => ({ type, date }));
  facts = [...vitalFacts, ...facts];

  const container = document.createDocumentFragment();
  if (facts.length) {
    const list = element("ol", { className: "fact-list" });
    facts.forEach((fact) => {
      if (typeof fact !== "object") {
        list.append(element("li", { className: "fact-card" }, [element("p", { className: "fact-label", text: "Fact" }), element("p", { className: "fact-detail", text: fact })]));
        return;
      }
      const date = legacyDateDisplay(firstValue(fact, ["date_display", "event_date_display", "date", "event_date", "fact_date", "legacy_date", "Date"]));
      const place = displayValue(firstValue(fact, ["place", "location", "event_place", "location_name", "Place"]));
      const detail = displayValue(firstValue(fact, ["description", "detail", "value", "cause", "address"]));
      const text = [date, place, detail].filter(Boolean).join(" · ") || "No further detail recorded.";
      list.append(element("li", { className: "fact-card" }, [
        element("p", { className: "fact-label", text: factTitle(fact) }),
        element("p", { className: "fact-detail", text })
      ]));
    });
    container.append(list);
  } else {
    container.append(element("p", { text: "No vital facts are recorded." }));
  }

  const notes = collectNotes(payload, facts);
  container.append(element("h4", { className: "notes-heading", text: "All notes" }));
  if (notes.length) {
    container.append(element("ol", { className: "notes-list" }, notes.map((note) => element("li", { text: note }))));
  } else {
    container.append(element("p", { text: "No notes are recorded." }));
  }
  elements.facts.replaceChildren(container);
}

function renderFamily(payload) {
  const groups = [
    ["Parents", ["parents", "parent"]],
    ["Spouses & partners", ["spouses", "partners", "spouse"]],
    ["Children", ["children", "child"]],
    ["Siblings", ["siblings", "brothers_sisters", "sibling"]]
  ];
  const sections = groups.map(([title, keys]) => {
    const people = listFrom(payload, keys);
    const list = element("ul");
    if (!people.length) list.append(element("li", { text: "None recorded" }));
    people.forEach((person) => {
      const button = element("button", { className: "family-person", type: "button" }, [
        document.createTextNode(personName(person)),
        element("span", { text: lifeSummary(person) })
      ]);
      button.addEventListener("click", () => openPerson(person));
      list.append(element("li", {}, button));
    });
    return element("section", { className: "family-group" }, [element("h4", { text: title }), list]);
  });
  elements.family.replaceChildren(...sections);
}

function renderSectionError(target, label, error) {
  target.replaceChildren(element("p", { text: `${label} could not be loaded: ${errorMessage(error)}` }));
}

function setRelationshipPerson(slot, person) {
  if (!personId(person)) return;
  if (slot === "A") state.personA = person;
  else state.personB = person;
  elements.relationshipResult.replaceChildren();
  setMessage(elements.relationshipState, `${personName(person)} assigned as person ${slot}.`);
  updateRelationshipCards();
}

function updateRelationshipCards() {
  updatePickCard(elements.personACard, "Person A", state.personA);
  updatePickCard(elements.personBCard, "Person B", state.personB);
  elements.relationshipButton.disabled = !(state.datasetId && personId(state.personA) && personId(state.personB));
}

function updatePickCard(card, label, person) {
  card.replaceChildren(
    element("span", { text: label }),
    element("strong", { text: person ? personName(person) : "Not selected" }),
    person ? element("small", { text: lifeSummary(person) }) : null
  );
}

async function findRelationship() {
  if (!personId(state.personA) || !personId(state.personB)) return;
  state.relationshipController?.abort();
  state.relationshipController = new AbortController();
  elements.relationshipResult.replaceChildren();
  setMessage(elements.relationshipState, "Tracing the shortest connection...");
  elements.relationshipButton.disabled = true;
  try {
    const params = new URLSearchParams({
      dataset_id: state.datasetId,
      from_person_id: personId(state.personA),
      to_person_id: personId(state.personB)
    });
    const payload = await api(`/api/relationship?${params}`, state.relationshipController);
    renderRelationship(payload);
    setMessage(elements.relationshipState, "");
  } catch (error) {
    const message = errorMessage(error);
    if (message) setMessage(elements.relationshipState, `Relationship could not be traced: ${message}`, "error");
  } finally {
    updateRelationshipCards();
  }
}

function renderRelationship(payload) {
  if (!payload || (payload.found === false) || payload.connected === false) {
    const reason = displayValue(firstValue(payload, ["reason", "message", "explanation"]));
    elements.relationshipResult.replaceChildren(element("p", { text: reason || "No relationship path was found in this collection." }));
    return;
  }
  const description = displayValue(firstValue(payload, ["explanation", "description", "relationship", "summary", "label"]));
  const distance = firstValue(payload, ["length", "distance", "degrees"]);
  const path = listFrom(payload, ["path", "people", "persons", "nodes"]);
  const contents = [
    element("h3", { text: "Shortest known connection" }),
    element("p", { text: description || `${personName(state.personA)} and ${personName(state.personB)} are connected by the path below.` })
  ];
  if (distance !== undefined) contents.push(element("p", { text: `${distance} ${Number(distance) === 1 ? "step" : "steps"}` }));
  if (path.length) {
    contents.push(element("ol", { className: "relationship-path" }, path.map((step) => {
      const relation = typeof step === "object" ? displayValue(firstValue(step, ["relationship", "relation", "role", "edge_label"])) : "";
      const label = typeof step === "object" ? personName(step.person || step.individual || step) : String(step);
      return element("li", { text: relation ? `${label} (${relation})` : label });
    })));
  }
  elements.relationshipResult.replaceChildren(...contents);
}

async function loadTree() {
  if (!state.currentPerson) return;
  state.treeController?.abort();
  state.treeController = new AbortController();
  const controller = state.treeController;
  elements.tree.replaceChildren();
  state.treeMap = null;
  state.treeSurface = null;
  setMessage(elements.treeState, "Loading family branches...");
  const mode = String(new FormData(elements.treeForm).get("direction") || "both");
  const generations = String(Math.max(1, Math.min(6, Number(elements.generations.value) || 3)));
  const id = personId(state.currentPerson);
  try {
    const directions = mode === "both" ? ["ancestors", "descendants"] : [mode];
    const requests = await Promise.allSettled(directions.map((direction) => {
      const params = new URLSearchParams({ direction, generations });
      const path = `/api/people/${encodeURIComponent(state.datasetId)}/${encodeURIComponent(id)}/tree?${params}`;
      return api(path, controller);
    }));
    if (controller.signal.aborted) return;
    const graphs = requests.map((request, index) => request.status === "fulfilled"
      ? linkedTreeGraph(request.value, directions[index])
      : null).filter(Boolean);
    if (!graphs.length) {
      const failure = requests.find((request) => request.status === "rejected");
      throw failure?.reason || new Error("No tree data was returned.");
    }
    renderPedigree(graphs, mode);
    const failedCount = requests.filter((request) => request.status === "rejected").length;
    setMessage(
      elements.treeState,
      failedCount
        ? "One tree direction could not be loaded; the available branch is shown."
        : "Select any card to focus that person. Scroll or drag the blank canvas to explore.",
      failedCount ? "error" : ""
    );
  } catch (error) {
    const message = errorMessage(error);
    if (message) setMessage(elements.treeState, `Tree could not be loaded: ${message}`, "error");
  }
}

function linkedTreeGraph(payload, direction) {
  const root = payload?.root || payload?.person;
  if (!root || !personId(root)) return null;
  const people = [root, ...listFrom(payload, ["people", "items"])]
    .filter((person) => person && personId(person));
  const byId = new Map(people.map((person) => [personId(person), person]));
  const levels = new Map();
  people.forEach((person) => {
    const depth = Number(firstValue(person, ["depth", "generation", "level"]) || 0);
    if (depth <= 0 || !Number.isFinite(depth)) return;
    if (!levels.has(depth)) levels.set(depth, new Map());
    levels.get(depth).set(personId(person), person);
  });
  listFrom(payload, ["generations"]).forEach((generation) => {
    const depth = Number(generation?.depth || 0);
    if (depth <= 0) return;
    if (!levels.has(depth)) levels.set(depth, new Map());
    listFrom(generation, ["people", "items"]).forEach((person) => {
      if (personId(person)) {
        byId.set(personId(person), person);
        levels.get(depth).set(personId(person), person);
      }
    });
  });
  const links = listFrom(payload, ["links", "edges"]).filter((link) => {
    const from = String(firstValue(link, ["from_person_id", "from", "source_id"]) ?? "");
    const to = String(firstValue(link, ["to_person_id", "to", "target_id"]) ?? "");
    return from && to && byId.has(from) && byId.has(to) && from !== to;
  });
  return { direction, root, byId, levels, links };
}

function generationLabel(direction, depth) {
  const position = direction === "ancestors" ? "above" : "below";
  return `Generation ${depth} ${position}`;
}

function pedigreeCard(person, context, focused = false) {
  const id = personId(person);
  const button = element("button", {
    className: `pedigree-card${focused ? " is-focused" : ""}`,
    type: "button"
  }, [
    element("span", { className: "pedigree-context", text: context }),
    element("strong", { text: personName(person) }),
    element("span", { className: "pedigree-lifespan", text: lifeSummary(person) })
  ]);
  button.setAttribute("aria-label", `${personName(person)}, ${lifeSummary(person)}. ${context}. Focus this person.`);
  button.addEventListener("click", () => openPerson(person));
  return button;
}

function renderPedigree(graphs, mode) {
  const root = graphs[0].root;
  const rootId = personId(root);
  const ancestorGraph = graphs.find((graph) => graph.direction === "ancestors");
  const descendantGraph = graphs.find((graph) => graph.direction === "descendants");
  const maxPeople = Math.max(1, ...graphs.flatMap((graph) =>
    [...graph.levels.values()].map((people) => people.size)));
  const surface = element("div", { className: "pedigree-surface" });
  const map = element("div", { className: "pedigree-map" });
  map.style.width = `${Math.max(760, maxPeople * 210)}px`;
  const lines = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  lines.setAttribute("class", "pedigree-lines");
  lines.setAttribute("aria-hidden", "true");
  map.append(lines);
  const cards = new Map();

  function addLevels(graph, depths) {
    depths.forEach((depth) => {
      const lane = element("section", { className: `pedigree-lane ${graph.direction}` });
      lane.setAttribute("aria-label", generationLabel(graph.direction, depth));
      for (const person of graph.levels.get(depth).values()) {
        const relation = displayValue(firstValue(person, ["relationship", "relation"]));
        const context = relation ? `${relation} · ${generationLabel(graph.direction, depth)}` : generationLabel(graph.direction, depth);
        const card = pedigreeCard(person, context);
        cards.set(`${graph.direction}\u0000${personId(person)}`, card);
        lane.append(card);
      }
      map.append(lane);
    });
  }

  if (ancestorGraph) addLevels(ancestorGraph, [...ancestorGraph.levels.keys()].sort((a, b) => b - a));
  const rootLane = element("section", { className: "pedigree-lane root" });
  const rootCard = pedigreeCard(root, "Focused person", true);
  cards.set(`root\u0000${rootId}`, rootCard);
  rootLane.append(rootCard);
  map.append(rootLane);
  if (descendantGraph) addLevels(descendantGraph, [...descendantGraph.levels.keys()].sort((a, b) => a - b));

  if ((!ancestorGraph || !ancestorGraph.levels.size) && (!descendantGraph || !descendantGraph.levels.size)) {
    rootLane.append(element("p", { className: "pedigree-empty", text: `No ${mode === "both" ? "ancestors or descendants" : mode} are recorded.` }));
  }
  surface.append(map);
  elements.tree.replaceChildren(surface);
  state.treeMap = map;
  state.treeSurface = surface;
  state.treeCards = cards;
  state.treeGraphs = graphs;
  state.treeRootId = rootId;
  state.treeScale = 1;
  updateTreeZoom(false);
  window.requestAnimationFrame(() => {
    drawTreeConnectors();
    centerTree();
  });
}

function treeCard(direction, id) {
  if (id === state.treeRootId) return state.treeCards?.get(`root\u0000${id}`);
  return state.treeCards?.get(`${direction}\u0000${id}`);
}

function drawTreeConnectors() {
  const map = state.treeMap;
  if (!map) return;
  const svg = map.querySelector(".pedigree-lines");
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${map.offsetWidth} ${map.offsetHeight}`);
  svg.setAttribute("width", String(map.offsetWidth));
  svg.setAttribute("height", String(map.offsetHeight));
  const drawn = new Set();
  function mapPosition(card) {
    let x = 0;
    let y = 0;
    let current = card;
    while (current && current !== map) {
      x += current.offsetLeft;
      y += current.offsetTop;
      current = current.offsetParent;
    }
    return { x, y };
  }
  state.treeGraphs.forEach((graph) => {
    graph.links.forEach((link) => {
      const fromId = String(firstValue(link, ["from_person_id", "from", "source_id"]) ?? "");
      const toId = String(firstValue(link, ["to_person_id", "to", "target_id"]) ?? "");
      const from = treeCard(graph.direction, fromId);
      const to = treeCard(graph.direction, toId);
      const marker = `${graph.direction}\u0000${fromId}\u0000${toId}`;
      if (!from || !to || drawn.has(marker)) return;
      drawn.add(marker);
      const upper = graph.direction === "ancestors" ? to : from;
      const lower = graph.direction === "ancestors" ? from : to;
      const upperPosition = mapPosition(upper);
      const lowerPosition = mapPosition(lower);
      const startX = upperPosition.x + upper.offsetWidth / 2;
      const startY = upperPosition.y + upper.offsetHeight;
      const endX = lowerPosition.x + lower.offsetWidth / 2;
      const endY = lowerPosition.y;
      const middleY = (startY + endY) / 2;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M ${startX} ${startY} V ${middleY} H ${endX} V ${endY}`);
      svg.append(path);
    });
  });
}

function updateTreeZoom(keepCenter = true) {
  if (!state.treeMap || !state.treeSurface) return;
  const viewport = elements.tree;
  const oldWidth = state.treeSurface.offsetWidth || 1;
  const oldHeight = state.treeSurface.offsetHeight || 1;
  const centerX = (viewport.scrollLeft + viewport.clientWidth / 2) / oldWidth;
  const centerY = (viewport.scrollTop + viewport.clientHeight / 2) / oldHeight;
  state.treeMap.style.transform = `scale(${state.treeScale})`;
  state.treeSurface.style.width = `${state.treeMap.offsetWidth * state.treeScale}px`;
  state.treeSurface.style.height = `${state.treeMap.offsetHeight * state.treeScale}px`;
  elements.treeZoomLevel.value = `${Math.round(state.treeScale * 100)}%`;
  elements.treeZoomLevel.textContent = `${Math.round(state.treeScale * 100)}%`;
  elements.treeZoomOut.disabled = state.treeScale <= 0.6;
  elements.treeZoomIn.disabled = state.treeScale >= 1.6;
  if (keepCenter) {
    viewport.scrollLeft = centerX * state.treeSurface.offsetWidth - viewport.clientWidth / 2;
    viewport.scrollTop = centerY * state.treeSurface.offsetHeight - viewport.clientHeight / 2;
  }
}

function changeTreeZoom(amount) {
  state.treeScale = Math.max(0.6, Math.min(1.6, Math.round((state.treeScale + amount) * 10) / 10));
  updateTreeZoom();
}

function centerTree() {
  const root = treeCard("root", state.treeRootId);
  if (!root || !state.treeSurface) return;
  let x = 0;
  let y = 0;
  let current = root;
  while (current && current !== state.treeMap) {
    x += current.offsetLeft;
    y += current.offsetTop;
    current = current.offsetParent;
  }
  elements.tree.scrollLeft = (x + root.offsetWidth / 2) * state.treeScale - elements.tree.clientWidth / 2;
  elements.tree.scrollTop = (y + root.offsetHeight / 2) * state.treeScale - elements.tree.clientHeight / 2;
}

function resetTreeView() {
  state.treeScale = 1;
  updateTreeZoom(false);
  centerTree();
}

function fullTreeReferenceId(value) {
  if (value && typeof value === "object") return personId(value);
  return value === undefined || value === null || value === "" ? "" : String(value);
}

function fullTreePath() {
  const params = new URLSearchParams();
  params.set("dataset", FULL_TREE_DATASET_ID);
  params.set("first", state.fullTreeFocus.firstId);
  if (state.fullTreeFocus.secondId) params.set("second", state.fullTreeFocus.secondId);
  params.set("generations", String(state.fullTreeGenerations));
  return `/api/full-tree?${params.toString()}`;
}

function fullTreeGraph(payload) {
  const byId = new Map();
  function addPerson(candidate) {
    if (!candidate || typeof candidate !== "object") return "";
    const id = fullTreeReferenceId(candidate);
    if (!id) return "";
    byId.set(id, { ...byId.get(id), ...candidate, person_id: id });
    return id;
  }
  listFrom(payload, ["people", "persons", "individuals", "items"]).forEach(addPerson);
  const roots = listFrom(payload, ["roots", "root_people"]).map(fullTreeReferenceId).filter(Boolean);

  const rawCouples = [];
  ["couples", "families", "marriages", "unions"].forEach((key) => {
    if (Array.isArray(payload?.[key])) rawCouples.push(...payload[key]);
  });
  listFrom(payload, ["generations"]).forEach((generation) => {
    ["couples", "families", "marriages", "unions"].forEach((key) => {
      if (Array.isArray(generation?.[key])) rawCouples.push(...generation[key]);
    });
  });

  const seenCouples = new Set();
  const couples = [];
  rawCouples.forEach((rawCouple, index) => {
    if (!rawCouple || typeof rawCouple !== "object") return;
    const rawId = firstValue(rawCouple, ["marriage_id", "family_id", "couple_id", "union_id", "id"]);
    const id = String(rawId === undefined || rawId === null ? `couple-${index + 1}` : rawId);
    if (seenCouples.has(id)) return;
    seenCouples.add(id);
    const partnerValues = [];
    ["partners", "spouses", "couple", "people"].forEach((key) => {
      if (Array.isArray(rawCouple[key])) partnerValues.push(...rawCouple[key]);
    });
    [
      "first_partner", "second_partner", "partner_1", "partner_2", "partner1", "partner2",
      "husband", "wife", "husband_reference", "wife_reference"
    ].forEach((key) => {
      if (rawCouple[key] !== undefined && rawCouple[key] !== null) partnerValues.push(rawCouple[key]);
    });
    ["partner_person_ids", "partner_ids", "person_ids", "spouse_ids"].forEach((key) => {
      if (Array.isArray(rawCouple[key])) partnerValues.push(...rawCouple[key]);
    });
    [
      "first_person_id", "second_person_id", "first_partner_id", "second_partner_id",
      "partner_1_id", "partner_2_id", "partner1_id", "partner2_id", "husband_person_id",
      "wife_person_id", "husband_individual_id", "wife_individual_id"
    ].forEach((key) => {
      if (rawCouple[key] !== undefined && rawCouple[key] !== null) partnerValues.push(rawCouple[key]);
    });
    const partnerIds = [];
    partnerValues.forEach((partner) => {
      const partnerId = addPerson(partner);
      if (partnerId && !partnerIds.includes(partnerId)) partnerIds.push(partnerId);
    });
    const childValues = [];
    ["children", "child_references"].forEach((key) => {
      if (Array.isArray(rawCouple[key])) childValues.push(...rawCouple[key]);
    });
    ["child_ids", "child_person_ids", "children_ids"].forEach((key) => {
      if (Array.isArray(rawCouple[key])) childValues.push(...rawCouple[key]);
    });
    const childIds = [];
    childValues.forEach((child) => {
      const childId = addPerson(child);
      if (childId && !childIds.includes(childId)) childIds.push(childId);
    });
    const alternatives = [];
    const rawAlternatives = Array.isArray(rawCouple.alternative_spouses)
      ? rawCouple.alternative_spouses
      : Array.isArray(rawCouple.alternative_partners)
        ? rawCouple.alternative_partners
        : [];
    rawAlternatives.forEach((alt) => {
      if (!alt || typeof alt !== "object") return;
      const spouse = alt.spouse && typeof alt.spouse === "object" ? alt.spouse : null;
      const spouseId = addPerson(spouse || firstValue(alt, ["spouse_person_id", "spouse_id", "person_id"]));
      if (!spouseId) return;
      alternatives.push({
        partnerId: fullTreeReferenceId(firstValue(alt, ["partner_person_id", "partner_id", "person_id"])),
        marriageId: fullTreeReferenceId(firstValue(alt, ["marriage_id", "family_id", "couple_id", "union_id"])),
        spouseId,
        person: byId.get(spouseId)
      });
    });
    const depth = Number(firstValue(rawCouple, ["depth", "generation", "level"]) ?? 0);
    const rootCouple = rawCouple.root_couple === true || rawCouple.is_root_couple === true || rawCouple.root_union === true;
    const marriageDate = displayValue(firstValue(rawCouple, [
      "marriage_date_display", "marriage_date", "marriage_sort_date", "marriage_date_text"
    ]));
    couples.push({
      id,
      depth: Number.isFinite(depth) && depth >= 0 ? depth : 0,
      rootCouple,
      partnerIds,
      childIds,
      alternatives,
      partners: partnerIds.map((id) => byId.get(id)).filter(Boolean),
      children: childIds.map((id) => byId.get(id)).filter(Boolean),
      marriageDate,
      raw: rawCouple
    });
  });

  const links = listFrom(payload, ["links", "edges"]).map((link) => ({
    childId: fullTreeReferenceId(firstValue(link, ["child_person_id", "child_id", "child_person", "child"])),
    coupleId: fullTreeReferenceId(firstValue(link, [
      "parent_couple_id", "parent_family_id", "parent_marriage_id", "parent_union_id",
      "marriage_id", "from_family_id", "source_family_id"
    ])),
    depth: Number(firstValue(link, ["depth", "generation", "level"]) ?? 0)
  })).filter((link) => link.childId && link.coupleId);

  const hasParents = new Set(
    listFrom(payload, ["has_parents", "people_with_parents", "expandable"])
      .map(fullTreeReferenceId)
      .filter(Boolean)
  );
  return {
    roots,
    byId,
    couples,
    links,
    hasParents,
    counts: payload?.counts || {},
    status: String(payload?.status || ""),
    message: displayValue(payload?.message),
    truncated: payload?.truncated === true,
    maxDepth: Number(firstValue(payload, ["max_depth", "generations"]) ?? 0)
  };
}

function ancestorCoupleById(graph) {
  const map = new Map();
  graph.couples.forEach((couple) => map.set(couple.id, couple));
  return map;
}

function layoutAncestorGraph(graph) {
  const coupleById = ancestorCoupleById(graph);
  const columns = new Map();
  const assigned = new Set();
  const queue = [];
  graph.couples.filter((couple) => couple.rootCouple).forEach((couple) => {
    queue.push({ id: couple.id, depth: couple.depth });
  });
  if (!queue.length && graph.couples.length) queue.push({ id: graph.couples[0].id, depth: 0 });
  let guard = 0;
  while (queue.length && guard < 2000) {
    guard += 1;
    const current = queue.shift();
    if (assigned.has(current.id)) continue;
    assigned.add(current.id);
    if (!columns.has(current.depth)) columns.set(current.depth, []);
    columns.get(current.depth).push(current.id);
    const couple = coupleById.get(current.id);
    if (!couple) continue;
    const parents = [];
    graph.links.forEach((link) => {
      if (!couple.partnerIds.includes(link.childId)) return;
      if (!coupleById.has(link.coupleId)) return;
      if (parents.includes(link.coupleId)) return;
      parents.push(link.coupleId);
    });
    parents.forEach((parentId) => {
      if (!assigned.has(parentId)) queue.push({ id: parentId, depth: current.depth + 1 });
    });
  }
  graph.couples.forEach((couple) => {
    if (assigned.has(couple.id)) return;
    if (!columns.has(couple.depth)) columns.set(couple.depth, []);
    columns.get(couple.depth).push(couple.id);
  });
  const depths = [...columns.keys()].sort((left, right) => left - right);
  return { columns, depths, coupleById };
}

function openFullTreePerson(person) {
  const id = personId(person);
  const datasetAvailable = Array.from(elements.dataset.options).some((option) => option.value === FULL_TREE_DATASET_ID);
  if (!id || !datasetAvailable) {
    setMessage(elements.fullTreeState, "This tree's record collection is not available, so the person record cannot be opened.", "error");
    return;
  }
  const route = { kind: "person", datasetId: FULL_TREE_DATASET_ID, personId: id };
  writeRoute(route);
  applyRoute(person);
}

function ancestorPersonWrap(person, showExpand) {
  const details = lifeSummary(person);
  const button = element("button", { className: "anc-person", type: "button" }, [
    element("strong", { text: personName(person) }),
    element("span", { text: details })
  ]);
  button.setAttribute("aria-label", `${personName(person)}, ${details}. Open person record.`);
  button.addEventListener("click", () => openFullTreePerson(person));
  const wrap = element("div", { className: "anc-person-wrap" }, [button]);
  if (showExpand) {
    const expand = element("button", { className: "anc-expand", type: "button" }, [
      element("span", { text: "Ancestors" }),
      element("small", { text: "›" })
    ]);
    expand.setAttribute("aria-label", `Show ancestors of ${personName(person)}`);
    expand.addEventListener("click", (event) => {
      event.stopPropagation();
      focusFullTreeOnPerson(person);
    });
    wrap.append(expand);
  }
  return wrap;
}

function ancestorMenuSelect(label, ariaLabel, items) {
  const select = element("select", { className: "anc-menu" });
  select.setAttribute("aria-label", ariaLabel);
  const placeholder = element("option", { text: `${label} (${items.length})` });
  placeholder.value = "";
  select.append(placeholder);
  items.forEach((person) => {
    const option = element("option", { text: personName(person) });
    option.value = personId(person);
    select.append(option);
  });
  select.addEventListener("change", () => {
    const chosen = select.value
      ? items.find((person) => personId(person) === select.value)
      : null;
    select.value = "";
    if (chosen) openFullTreePerson(chosen);
  });
  return element("label", { className: "anc-menu-label" }, [element("span", { text: label }), select]);
}

function ancestorCoupleCard(couple, terminal) {
  const card = element("article", { className: `anc-couple${couple.rootCouple ? " is-root" : ""}` });
  card.dataset.coupleId = couple.id;
  const header = element("div", { className: "anc-couple-header" }, [
    element("span", { text: couple.rootCouple ? "Couple" : "Parents" }),
    couple.marriageDate ? element("small", { text: couple.marriageDate }) : null
  ]);
  const cardsRow = element("div", { className: "anc-couple-cards" });
  if (!couple.partnerIds.length) {
    cardsRow.append(element("div", { className: "missing-partner", text: "Partner not recorded" }));
  } else {
    couple.partners.forEach((person, index) => {
      const showExpand = terminal && person && state.fullTreeHasParents.has(personId(person));
      const wrap = ancestorPersonWrap(person, showExpand);
      wrap.classList.add(index % 2 === 0 ? "is-first" : "is-second");
      cardsRow.append(wrap);
    });
  }
  card.append(header, cardsRow);
  const actions = element("div", { className: "anc-couple-actions" });
  if (couple.children.length) {
    actions.append(ancestorMenuSelect("Children", "Children of this couple", couple.children));
  }
  if (couple.alternatives.length) {
    actions.append(ancestorMenuSelect("Other spouses", "Other recorded spouses", couple.alternatives.map((alt) => alt.person).filter(Boolean)));
  }
  card.append(actions);
  return card;
}

function renderFullTree(payload) {
  const graph = fullTreeGraph(payload);
  state.fullTreeGraph = graph;
  state.fullTreePeople = graph.byId;
  state.fullTreeRoots = graph.roots;
  state.fullTreeHasParents = graph.hasParents;
  const rootPeople = graph.roots.map((id) => graph.byId.get(id)).filter(Boolean);
  if (
    rootPeople.length >= 2
    && graph.roots.includes(FULL_TREE_ROOT_IDS[0])
    && graph.roots.includes(FULL_TREE_ROOT_IDS[1])
  ) {
    state.fullTreeRootLabel = `${personName(rootPeople[0])} & ${personName(rootPeople[1])}`;
    if (!state.fullTreeFocusStack.length) state.fullTreeFocusLabel = state.fullTreeRootLabel;
  }
  const layout = layoutAncestorGraph(graph);
  state.fullTreeLayout = layout;
  elements.fullTree.replaceChildren();
  elements.fullTreeSummary.replaceChildren();
  updateFullTreeBreadcrumbs();

  if (!graph.couples.length) {
    const message = graph.status === "no_shared_couple"
      ? (graph.message || "These people do not share a recorded couple in this dataset.")
      : "No couple records were returned for these roots.";
    elements.fullTree.append(element("div", { className: "full-tree-empty" }, [
      element("p", { className: "folio", text: "No couple" }),
      element("h3", { text: graph.roots.length >= 2 ? "No shared couple" : "No ancestors" }),
      element("p", { text: message })
    ]));
    setMessage(elements.fullTreeState, message, "error");
    return;
  }

  const depths = layout.depths;
  const maxShownDepth = depths.length ? depths[depths.length - 1] : 0;
  const maxRows = Math.max(1, ...depths.map((depth) => layout.columns.get(depth).length));
  const mapWidth = FULL_TREE_PAD_X * 2 + (depths.length - 1) * (FULL_TREE_COUPLE_WIDTH + FULL_TREE_COLUMN_GAP) + FULL_TREE_COUPLE_WIDTH;
  const mapHeight = FULL_TREE_PAD_Y * 2 + maxRows * FULL_TREE_ROW_HEIGHT;
  const map = element("div", { className: "full-tree-map" });
  map.style.width = `${mapWidth}px`;
  map.style.height = `${mapHeight}px`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "full-tree-lines");
  svg.setAttribute("aria-hidden", "true");
  map.append(svg);
  const coupleCards = new Map();
  depths.forEach((depth) => {
    const x = FULL_TREE_PAD_X + depth * (FULL_TREE_COUPLE_WIDTH + FULL_TREE_COLUMN_GAP);
    const marker = element("div", { className: "full-tree-column-marker" }, [
      element("span", { text: depth === 0 ? "Couple" : `Generation ${depth}` })
    ]);
    marker.style.left = `${x}px`;
    map.append(marker);
    layout.columns.get(depth).forEach((coupleId, row) => {
      const couple = layout.coupleById.get(coupleId);
      if (!couple) return;
      const card = ancestorCoupleCard(couple, depth === maxShownDepth);
      card.style.left = `${x}px`;
      card.style.top = `${FULL_TREE_PAD_Y + row * FULL_TREE_ROW_HEIGHT}px`;
      card.style.width = `${FULL_TREE_COUPLE_WIDTH}px`;
      coupleCards.set(coupleId, card);
      map.append(card);
    });
  });
  elements.fullTree.append(map);
  state.fullTreeMap = map;
  state.fullTreeCoupleCards = coupleCards;
  state.fullTreeTransform = { x: 0, y: 0, scale: 1 };
  applyFullTreeTransform();

  const peopleCount = Number(firstValue(graph.counts, ["people", "person_count", "individuals"])) || graph.byId.size;
  const coupleCount = Number(firstValue(graph.counts, ["couples", "families", "marriage_count", "marriages"])) || graph.couples.length;
  elements.fullTreeSummary.replaceChildren(
    element("strong", { text: `${peopleCount} people` }),
    element("span", { text: `${coupleCount} couples · generation 0–${maxShownDepth}` })
  );
  const warnings = [];
  if (graph.truncated) {
    warnings.push("Earlier ancestors exist. Page Older for more generations, or expand a person to follow one line.");
  }
  if (graph.message) warnings.push(graph.message);
  setMessage(
    elements.fullTreeState,
    warnings.join(" ") || "Drag the canvas, zoom, open a person, or page Older to go further back.",
    warnings.length ? "error" : ""
  );
  window.requestAnimationFrame(() => {
    drawFullTreeConnectors();
    centerFullTree();
  });
}

function ancestorLayoutPosition(node, map) {
  let x = 0;
  let y = 0;
  let current = node;
  while (current && current !== map) {
    x += current.offsetLeft;
    y += current.offsetTop;
    current = current.offsetParent;
  }
  return { x, y };
}

function drawFullTreeConnectors() {
  const map = state.fullTreeMap;
  const graph = state.fullTreeGraph;
  if (!map || !graph) return;
  const svg = map.querySelector(".full-tree-lines");
  svg.replaceChildren();
  const width = map.offsetWidth || 1;
  const height = map.offsetHeight || 1;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  const homeCardByPerson = new Map();
  graph.couples.forEach((couple) => {
    const card = state.fullTreeCoupleCards.get(couple.id);
    if (!card) return;
    couple.partnerIds.forEach((partnerId, index) => {
      if (!homeCardByPerson.has(partnerId)) homeCardByPerson.set(partnerId, { card, index });
    });
  });
  graph.links.forEach((link) => {
    const parentCard = state.fullTreeCoupleCards.get(link.coupleId);
    const childHome = homeCardByPerson.get(link.childId);
    if (!parentCard || !childHome) return;
    const childPerson = childHome.card.querySelectorAll(".anc-person")[childHome.index];
    const parentPerson = parentCard.querySelector(".anc-person");
    if (!childPerson || !parentPerson) return;
    const start = ancestorLayoutPosition(childPerson, map);
    const startX = start.x + childPerson.offsetWidth;
    const startY = start.y + childPerson.offsetHeight / 2;
    const end = ancestorLayoutPosition(parentPerson, map);
    const endX = end.x;
    const endY = end.y + parentPerson.offsetHeight / 2;
    const curve = Math.max(24, (endX - startX) / 2);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`);
    svg.append(path);
  });
}

function applyFullTreeTransform() {
  const map = state.fullTreeMap;
  if (!map) return;
  const transform = state.fullTreeTransform;
  transform.scale = Math.max(0.5, Math.min(2, transform.scale));
  map.style.transform = `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`;
  map.style.transformOrigin = "0 0";
  elements.fullTreeZoomLevel.value = `${Math.round(transform.scale * 100)}%`;
  elements.fullTreeZoomLevel.textContent = `${Math.round(transform.scale * 100)}%`;
  elements.fullTreeZoomOut.disabled = transform.scale <= 0.5;
  elements.fullTreeZoomIn.disabled = transform.scale >= 2;
}

function changeFullTreeZoom(amount) {
  const viewport = elements.fullTree;
  const transform = state.fullTreeTransform;
  const centerX = (viewport.clientWidth / 2 - transform.x) / transform.scale;
  const centerY = (viewport.clientHeight / 2 - transform.y) / transform.scale;
  transform.scale = Math.max(0.5, Math.min(2, transform.scale + amount));
  transform.x = viewport.clientWidth / 2 - centerX * transform.scale;
  transform.y = viewport.clientHeight / 2 - centerY * transform.scale;
  applyFullTreeTransform();
}

function centerFullTree() {
  const map = state.fullTreeMap;
  if (!map) return;
  const root = map.querySelector(".anc-couple.is-root") || map.querySelector(".anc-couple");
  if (!root) return;
  const viewport = elements.fullTree;
  const transform = state.fullTreeTransform;
  transform.x = viewport.clientWidth / 2 - (root.offsetLeft + root.offsetWidth / 2) * transform.scale;
  transform.y = viewport.clientHeight / 2 - (root.offsetTop + root.offsetHeight / 2) * transform.scale;
  applyFullTreeTransform();
}

function resetFullTreeView() {
  state.fullTreeTransform.scale = 1;
  centerFullTree();
}

function focusFullTreeOnPerson(person) {
  const id = personId(person);
  if (!id || !validRouteId(id)) return;
  state.fullTreeFocusStack.push({
    firstId: state.fullTreeFocus.firstId,
    secondId: state.fullTreeFocus.secondId || null,
    label: state.fullTreeFocusLabel || state.fullTreeRootLabel
  });
  state.fullTreeFocus = { firstId: id, secondId: null };
  state.fullTreeFocusLabel = personName(person);
  state.fullTreeGenerations = FULL_TREE_DEFAULT_GENERATIONS;
  state.fullTreeMap = null;
  loadFullTree();
}

function resetFullTreeFocus() {
  state.fullTreeFocusStack = [];
  state.fullTreeFocus = { firstId: FULL_TREE_ROOT_IDS[0], secondId: FULL_TREE_ROOT_IDS[1] };
  state.fullTreeFocusLabel = state.fullTreeRootLabel;
  state.fullTreeGenerations = FULL_TREE_DEFAULT_GENERATIONS;
  state.fullTreeMap = null;
  loadFullTree();
}

function updateFullTreeBreadcrumbs() {
  const container = elements.fullTreeBreadcrumbs;
  if (!container) return;
  container.replaceChildren();
  if (!state.fullTreeFocusStack.length) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const crumbs = [
    { label: state.fullTreeRootLabel, firstId: FULL_TREE_ROOT_IDS[0], secondId: FULL_TREE_ROOT_IDS[1], kind: "root" },
    ...state.fullTreeFocusStack.map((entry) => ({
      label: entry.label, firstId: entry.firstId, secondId: entry.secondId, kind: "focus"
    }))
  ];
  crumbs.forEach((crumb) => {
    container.append(element("span", { className: "anc-crumb-sep", text: "›" }));
    const button = element("button", { className: "anc-crumb", type: "button", text: crumb.label });
    button.addEventListener("click", () => {
      if (crumb.kind === "root") {
        resetFullTreeFocus();
        return;
      }
      const cut = state.fullTreeFocusStack.findIndex(
        (entry) => entry.firstId === crumb.firstId && (entry.secondId || null) === crumb.secondId
      );
      state.fullTreeFocusStack = cut >= 0 ? state.fullTreeFocusStack.slice(0, cut) : [];
      state.fullTreeFocus = { firstId: crumb.firstId, secondId: crumb.secondId };
      state.fullTreeFocusLabel = crumb.label;
      state.fullTreeGenerations = FULL_TREE_DEFAULT_GENERATIONS;
      state.fullTreeMap = null;
      loadFullTree();
    });
    container.append(button);
  });
  container.append(element("span", { className: "anc-crumb-sep", text: "›" }));
  container.append(element("span", { className: "anc-crumb-current", text: state.fullTreeFocusLabel || state.fullTreeRootLabel }));
}

function updateFullTreePagination() {
  elements.fullTreeGenerations.textContent = `Showing generations 0–${state.fullTreeGenerations}`;
  elements.fullTreeOlder.disabled = state.fullTreeGenerations >= FULL_TREE_MAX_GENERATIONS;
  elements.fullTreeNewer.disabled = state.fullTreeGenerations <= FULL_TREE_MIN_GENERATIONS;
}

function pageFullTreeAncestors(amount) {
  state.fullTreeGenerations = Math.max(
    FULL_TREE_MIN_GENERATIONS,
    Math.min(FULL_TREE_MAX_GENERATIONS, state.fullTreeGenerations + amount)
  );
  state.fullTreeMap = null;
  loadFullTree();
}

async function loadFullTree() {
  const loadKey = `${state.sourceVersion}:${state.transport}:${state.fullTreeFocus.firstId}:${state.fullTreeFocus.secondId || ""}:${state.fullTreeGenerations}`;
  if (state.fullTreeLoadKey === loadKey && state.fullTreeMap) return;
  state.fullTreeController?.abort();
  state.fullTreeController = new AbortController();
  const controller = state.fullTreeController;
  state.fullTreeLoadKey = loadKey;
  state.fullTreeMap = null;
  elements.fullTree.replaceChildren();
  elements.fullTreeSummary.replaceChildren();
  updateFullTreePagination();
  setMessage(elements.fullTreeState, "Loading ancestors...");
  try {
    const payload = await api(fullTreePath(), controller);
    if (controller.signal.aborted || parseRoute().kind !== "full-tree") return;
    renderFullTree(payload);
  } catch (error) {
    if (controller.signal.aborted) return;
    state.fullTreeLoadKey = "";
    const message = errorMessage(error);
    if (message) setMessage(elements.fullTreeState, `Family tree could not be loaded: ${message}`, "error");
  }
}

elements.databaseFile.addEventListener("change", async () => {
  const file = elements.databaseFile.files?.[0];
  await openSelectedFile(file);
  elements.databaseFile.value = "";
});
elements.dataset.addEventListener("change", () => {
  writeRoute({ kind: "root" });
  state.lastPeopleRoute = { kind: "root" };
  showTopLevelView("people");
  resetForDataset();
  loadBrowsePage(0);
});
elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(state.searchTimer);
  searchPeople(elements.searchInput.value);
});
elements.searchInput.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.catalogController?.abort();
  state.catalogRequestId += 1;
  state.catalogBusy = false;
  const query = elements.searchInput.value;
  if (!query.trim()) {
    showCurrentBrowsePage();
    return;
  }
  state.catalogMode = "search";
  updateCatalogControls();
  state.searchTimer = setTimeout(() => searchPeople(query), 350);
});
elements.browseAll.addEventListener("click", () => {
  clearTimeout(state.searchTimer);
  elements.searchInput.value = "";
  loadBrowsePage(0);
});
elements.browsePrevious.addEventListener("click", () => {
  loadBrowsePage(Math.max(0, state.browseOffset - BROWSE_PAGE_SIZE));
});
elements.browseNext.addEventListener("click", () => {
  if (state.browseHasMore) loadBrowsePage(state.browseOffset + BROWSE_PAGE_SIZE);
});
elements.setPersonA.addEventListener("click", () => setRelationshipPerson("A", state.currentPerson));
elements.setPersonB.addEventListener("click", () => setRelationshipPerson("B", state.currentPerson));
elements.relationshipButton.addEventListener("click", findRelationship);
elements.treeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadTree();
});
elements.treeZoomOut.addEventListener("click", () => changeTreeZoom(-0.1));
elements.treeZoomIn.addEventListener("click", () => changeTreeZoom(0.1));
elements.treeZoomReset.addEventListener("click", resetTreeView);
elements.fullTreeZoomOut.addEventListener("click", () => changeFullTreeZoom(-0.1));
elements.fullTreeZoomIn.addEventListener("click", () => changeFullTreeZoom(0.1));
elements.fullTreeZoomReset.addEventListener("click", resetFullTreeView);
elements.fullTreeReset.addEventListener("click", resetFullTreeFocus);
elements.fullTreeOlder.addEventListener("click", () => pageFullTreeAncestors(1));
elements.fullTreeNewer.addEventListener("click", () => pageFullTreeAncestors(-1));

function selectTopLevelTab(view) {
  const route = view === "full-tree" ? { kind: "full-tree" } : state.lastPeopleRoute;
  if (parseRoute().kind === route.kind) return;
  writeRoute(route);
  applyRoute();
}

elements.peopleTab.addEventListener("click", () => selectTopLevelTab("people"));
elements.fullTreeTab.addEventListener("click", () => selectTopLevelTab("full-tree"));
[elements.peopleTab, elements.fullTreeTab].forEach((tab, index, tabs) => {
  tab.addEventListener("keydown", (event) => {
    let next = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    tabs[next].focus();
    tabs[next].click();
  });
});

let pan = null;
elements.tree.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || event.target.closest("button")) return;
  pan = {
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    left: elements.tree.scrollLeft,
    top: elements.tree.scrollTop
  };
  elements.tree.setPointerCapture(event.pointerId);
  elements.tree.classList.add("is-panning");
});
elements.tree.addEventListener("pointermove", (event) => {
  if (!pan || pan.pointerId !== event.pointerId) return;
  elements.tree.scrollLeft = pan.left - (event.clientX - pan.x);
  elements.tree.scrollTop = pan.top - (event.clientY - pan.y);
});
function endTreePan(event) {
  if (!pan || pan.pointerId !== event.pointerId) return;
  pan = null;
  elements.tree.classList.remove("is-panning");
}
elements.tree.addEventListener("pointerup", endTreePan);
elements.tree.addEventListener("pointercancel", endTreePan);

let fullTreePan = null;
elements.fullTree.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || event.target.closest("button, select, a")) return;
  const transform = state.fullTreeTransform;
  fullTreePan = {
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    tx: transform.x,
    ty: transform.y
  };
  elements.fullTree.setPointerCapture(event.pointerId);
  elements.fullTree.classList.add("is-panning");
});
elements.fullTree.addEventListener("pointermove", (event) => {
  if (!fullTreePan || fullTreePan.pointerId !== event.pointerId) return;
  state.fullTreeTransform.x = fullTreePan.tx + (event.clientX - fullTreePan.x);
  state.fullTreeTransform.y = fullTreePan.ty + (event.clientY - fullTreePan.y);
  applyFullTreeTransform();
});
function endFullTreePan(event) {
  if (!fullTreePan || fullTreePan.pointerId !== event.pointerId) return;
  fullTreePan = null;
  elements.fullTree.classList.remove("is-panning");
}
elements.fullTree.addEventListener("pointerup", endFullTreePan);
elements.fullTree.addEventListener("pointercancel", endFullTreePan);
elements.fullTree.addEventListener("keydown", (event) => {
  const distance = event.shiftKey ? 220 : 70;
  const movement = {
    ArrowLeft: [distance, 0],
    ArrowRight: [-distance, 0],
    ArrowUp: [0, distance],
    ArrowDown: [0, -distance]
  }[event.key];
  if (!movement || event.target.closest("button, select")) return;
  event.preventDefault();
  state.fullTreeTransform.x += movement[0];
  state.fullTreeTransform.y += movement[1];
  applyFullTreeTransform();
});

let routeSyncQueued = false;
function queueRouteSync() {
  if (routeSyncQueued) return;
  routeSyncQueued = true;
  window.setTimeout(() => {
    routeSyncQueued = false;
    applyRoute();
  }, 0);
}
window.addEventListener("popstate", queueRouteSync);
window.addEventListener("hashchange", queueRouteSync);
window.addEventListener("resize", () => window.requestAnimationFrame(() => {
  drawTreeConnectors();
  drawFullTreeConnectors();
}));

if (window.matchMedia("(max-width: 560px)").matches) elements.generations.value = "2";

initialize();
