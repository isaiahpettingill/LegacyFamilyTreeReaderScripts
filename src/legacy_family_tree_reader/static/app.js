"use strict";

const elements = {
  appStatus: document.querySelector("#app-status"),
  dataset: document.querySelector("#dataset-select"),
  searchForm: document.querySelector("#search-form"),
  searchInput: document.querySelector("#search-input"),
  searchButton: document.querySelector("#search-form button"),
  searchState: document.querySelector("#search-state"),
  searchResults: document.querySelector("#search-results"),
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
  personACard: document.querySelector("#person-a-card"),
  personBCard: document.querySelector("#person-b-card"),
  relationshipButton: document.querySelector("#find-relationship"),
  relationshipState: document.querySelector("#relationship-state"),
  relationshipResult: document.querySelector("#relationship-result")
};

const state = {
  datasetId: "",
  currentPerson: null,
  personA: null,
  personB: null,
  searchTimer: null,
  searchController: null,
  recordController: null,
  treeController: null,
  relationshipController: null
};

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

function lifeSummary(person) {
  if (!person || typeof person !== "object") return "";
  const direct = firstValue(person, ["lifespan", "life_span", "dates"]);
  if (direct && typeof direct !== "object") return String(direct);
  const birth = displayValue(firstValue(person, ["birth_date_display", "birth_legacy_date", "birth_date", "birth", "date_of_birth", "BirthDate"]));
  const death = displayValue(firstValue(person, ["death_date_display", "death_legacy_date", "death_date", "death", "date_of_death", "DeathDate"]));
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

async function api(path, controller) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    signal: controller?.signal
  });
  let data;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = firstValue(data, ["detail", "message", "error"]);
    throw new Error(detail ? displayValue(detail) : `Request failed (${response.status})`);
  }
  return data;
}

function errorMessage(error) {
  if (error?.name === "AbortError") return "";
  return error instanceof Error ? error.message : "The archive could not complete this request.";
}

async function loadDatasets() {
  setMessage(elements.appStatus, "Opening the archive...");
  try {
    const payload = await api("/api/datasets");
    let datasets = listFrom(payload, ["datasets", "items", "results"]);
    if (!datasets.length && payload && typeof payload === "object" && datasetId(payload)) datasets = [payload];
    elements.dataset.replaceChildren();
    if (!datasets.length) {
      elements.dataset.append(element("option", { text: "No collections available" }));
      setMessage(elements.appStatus, "No family record collections are available.", "error");
      return;
    }
    datasets.forEach((dataset) => {
      const option = element("option", { text: datasetName(dataset) });
      option.value = datasetId(dataset) || datasetName(dataset);
      elements.dataset.append(option);
    });
    elements.dataset.disabled = false;
    elements.searchInput.disabled = false;
    elements.searchButton.disabled = false;
    state.datasetId = elements.dataset.value;
    setMessage(elements.appStatus, "");
    elements.searchInput.focus();
  } catch (error) {
    elements.dataset.replaceChildren(element("option", { text: "Collections unavailable" }));
    setMessage(elements.appStatus, `Could not open collections: ${errorMessage(error)}`, "error");
  }
}

function resetForDataset() {
  state.datasetId = elements.dataset.value;
  state.currentPerson = null;
  state.personA = null;
  state.personB = null;
  state.searchController?.abort();
  state.recordController?.abort();
  state.treeController?.abort();
  state.relationshipController?.abort();
  elements.searchInput.value = "";
  elements.searchResults.replaceChildren();
  elements.recordContent.hidden = true;
  elements.recordEmpty.hidden = false;
  elements.relationshipResult.replaceChildren();
  setMessage(elements.searchState, "Search this collection by name.");
  setMessage(elements.recordState);
  setMessage(elements.treeState);
  setMessage(elements.relationshipState);
  updateRelationshipCards();
  elements.searchInput.focus();
}

async function searchPeople(query) {
  const trimmed = query.trim();
  state.searchController?.abort();
  elements.searchResults.replaceChildren();
  if (!trimmed) {
    setMessage(elements.searchState, "Enter part of a name to search.");
    return;
  }
  state.searchController = new AbortController();
  setMessage(elements.searchState, "Searching the index...");
  try {
    const params = new URLSearchParams({ dataset_id: state.datasetId, q: trimmed, limit: "50" });
    const payload = await api(`/api/people/search?${params}`, state.searchController);
    const people = listFrom(payload, ["people", "results", "items", "matches"]);
    renderSearchResults(people);
    setMessage(elements.searchState, people.length ? `${people.length} ${people.length === 1 ? "person" : "people"} found.` : "No matching people found. Try fewer letters or another spelling.");
  } catch (error) {
    const message = errorMessage(error);
    if (message) setMessage(elements.searchState, `Search failed: ${message}`, "error");
  }
}

function renderSearchResults(people) {
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

async function openPerson(summary) {
  const id = personId(summary);
  if (!id) {
    setMessage(elements.searchState, "This search result has no person identifier.", "error");
    return;
  }
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
  setMessage(elements.treeState, "Choose a direction and draw the tree.");

  const base = `/api/people/${encodeURIComponent(state.datasetId)}/${encodeURIComponent(id)}`;
  const signal = state.recordController;
  const requests = await Promise.allSettled([
    api(base, signal),
    api(`${base}/facts`, signal),
    api(`${base}/family`, signal)
  ]);
  if (signal.signal.aborted) return;

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
    ["Sex", ["gender_code", "sex", "gender"]],
    ["Birth", ["birth_legacy_date", "birth_date", "birth", "date_of_birth"]],
    ["Birthplace", ["birth_place", "place_of_birth"]],
    ["Death", ["death_legacy_date", "death_date", "death", "date_of_death"]],
    ["Death place", ["death_place", "place_of_death"]],
    ["Burial", ["burial_date", "burial"]],
    ["Burial place", ["burial_place", "cemetery"]],
    ["Legacy RIN", ["legacy_rin"]],
    ["Record ID", ["person_id", "id", "individual_id"]]
  ];
  const rows = [];
  const seen = new Set();
  fields.forEach(([label, keys]) => {
    const text = displayValue(firstValue(person, keys));
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
    ["Birth", firstValue(identity, ["birth_legacy_date", "birth_date", "date_of_birth"])],
    ["Death", firstValue(identity, ["death_legacy_date", "death_date", "date_of_death"])]
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
      const date = displayValue(firstValue(fact, ["date", "event_date", "fact_date", "legacy_date", "Date"]));
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
  elements.tree.replaceChildren();
  setMessage(elements.treeState, "Drawing family tree...");
  const direction = new FormData(elements.treeForm).get("direction") || "ancestors";
  const generations = elements.generations.value;
  const id = personId(state.currentPerson);
  try {
    const params = new URLSearchParams({ direction: String(direction), generations });
    const path = `/api/people/${encodeURIComponent(state.datasetId)}/${encodeURIComponent(id)}/tree?${params}`;
    const payload = await api(path, state.treeController);
    renderTree(payload, String(direction));
    setMessage(elements.treeState, "Select a branch to collapse or expand it.");
  } catch (error) {
    const message = errorMessage(error);
    if (message) setMessage(elements.treeState, `Tree could not be loaded: ${message}`, "error");
  }
}

function treeChildren(node, direction) {
  if (!node || typeof node !== "object") return [];
  const keys = direction === "ancestors"
    ? ["parents", "ancestors", "children", "branches"]
    : ["children", "descendants", "branches"];
  return listFrom(node, keys);
}

function renderTree(payload, direction) {
  if (payload?.root && Array.isArray(payload.people) && Array.isArray(payload.links)) {
    renderLinkedTree(payload, direction);
    return;
  }
  const directList = Array.isArray(payload) ? payload : null;
  const nodes = directList || listFrom(payload, ["generations", "items"]);
  if (nodes.length && nodes.every((node) => Array.isArray(node.people))) {
    const flattened = nodes.flatMap((generation) => generation.people.map((person) => ({
      ...person,
      depth: generation.depth
    })));
    renderFlatTree([payload.root, ...flattened].filter(Boolean));
    return;
  }
  if (nodes.length && nodes.some((node) => firstValue(node, ["generation", "depth", "level"]) !== undefined)) {
    renderFlatTree(nodes);
    return;
  }

  let root = payload?.root || payload?.tree || payload;
  if (root?.person && !treeChildren(root, direction).length && treeChildren(root.person, direction).length) root = root.person;
  if (!root || (typeof root === "object" && !Object.keys(root).length)) {
    elements.tree.replaceChildren(element("p", { text: `No ${direction} are recorded.` }));
    return;
  }
  const branch = renderTreeNode(root, direction, 0);
  elements.tree.replaceChildren(branch);
}

function renderTreeNode(node, direction, depth) {
  const person = node?.person || node?.individual || node;
  const children = treeChildren(node, direction);
  const personButton = element("button", { className: "tree-person", type: "button" }, [
    document.createTextNode(personName(person)),
    element("span", { text: lifeSummary(person) })
  ]);
  if (personId(person)) {
    personButton.setAttribute("aria-label", `Open record for ${personName(person)}`);
    personButton.addEventListener("click", () => openPerson(person));
  }
  else personButton.disabled = true;

  if (!children.length) return element("div", { className: "tree-leaf" }, personButton);
  const details = element("details");
  details.open = depth < 2;
  const summary = element("summary");
  summary.append(element("span", { className: "tree-summary" }, [
    document.createTextNode(personName(person)),
    element("span", { text: lifeSummary(person) })
  ]));
  details.append(summary);
  if (personId(person)) details.append(personButton);
  children.forEach((child) => details.append(renderTreeNode(child, direction, depth + 1)));
  return details;
}

function renderLinkedTree(payload, direction) {
  const allPeople = [payload.root, ...payload.people];
  const byId = new Map(allPeople.map((person) => [personId(person), person]));
  const childrenById = new Map();
  payload.links.forEach((link) => {
    const from = String(firstValue(link, ["from_person_id", "from", "source_id"]) ?? "");
    const to = String(firstValue(link, ["to_person_id", "to", "target_id"]) ?? "");
    if (!from || !to || !byId.has(to)) return;
    if (!childrenById.has(from)) childrenById.set(from, []);
    const person = { ...byId.get(to) };
    if (!person.relationship && link.relationship) person.relationship = link.relationship;
    childrenById.get(from).push(person);
  });

  function branch(person, seen = new Set()) {
    const id = personId(person);
    if (seen.has(id)) return person;
    const nextSeen = new Set(seen);
    nextSeen.add(id);
    const children = (childrenById.get(id) || []).map((child) => branch(child, nextSeen));
    return { person, [direction]: children };
  }

  const rootBranch = branch(payload.root);
  const rootNode = renderTreeNode(rootBranch, direction, 0);
  if (!treeChildren(rootBranch, direction).length) {
    elements.tree.replaceChildren(
      element("p", { text: `No ${direction} are recorded for this person.` }),
      rootNode
    );
  } else {
    elements.tree.replaceChildren(rootNode);
  }
}

function renderFlatTree(nodes) {
  const groups = new Map();
  nodes.forEach((node) => {
    const depth = Number(firstValue(node, ["generation", "depth", "level"]) || 0);
    if (!groups.has(depth)) groups.set(depth, []);
    groups.get(depth).push(node.person || node.individual || node);
  });
  const sections = [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([depth, people]) => {
    const list = element("ul");
    people.forEach((person) => {
      const button = element("button", { className: "family-person", type: "button", text: personName(person) });
      if (personId(person)) button.addEventListener("click", () => openPerson(person));
      else button.disabled = true;
      list.append(element("li", {}, button));
    });
    return element("section", { className: "generation-list" }, [element("h4", { text: depth === 0 ? "Starting person" : `Generation ${depth}` }), list]);
  });
  elements.tree.replaceChildren(...sections);
}

elements.dataset.addEventListener("change", resetForDataset);
elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(state.searchTimer);
  searchPeople(elements.searchInput.value);
});
elements.searchInput.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  const query = elements.searchInput.value;
  if (!query.trim()) {
    state.searchController?.abort();
    elements.searchResults.replaceChildren();
    setMessage(elements.searchState, "Enter part of a name to search.");
    return;
  }
  state.searchTimer = setTimeout(() => searchPeople(query), 350);
});
elements.setPersonA.addEventListener("click", () => setRelationshipPerson("A", state.currentPerson));
elements.setPersonB.addEventListener("click", () => setRelationshipPerson("B", state.currentPerson));
elements.relationshipButton.addEventListener("click", findRelationship);
elements.treeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadTree();
});

loadDatasets();
