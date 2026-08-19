"use strict";

(function (global) {
  let database = null;

  const PERSON_ALIASES = {
    person_id: "individual_id",
    legacy_rin: "legacy_id",
    given_names: "given_name",
    title_prefix: "prefix",
    title_suffix: "title",
    gender_code: "gender",
    birth_legacy_date: "birth_date",
    birth_sort_date_key: "birth_sort_date",
    death_legacy_date: "death_date",
    death_sort_date_key: "death_sort_date",
    living_flag: "living",
    private_flag: "private",
    general_notes: "notes",
    research_notes: "references",
    medical_notes: "medical",
    cause_of_death: "death_cause"
  };

  const PERSON_REFERENCE_FIELDS = [
    "dataset_id", "person_id", "legacy_rin", "display_name", "title_prefix",
    "given_names", "surname", "title_suffix", "gender_code", "birth_legacy_date",
    "birth_sort_date_key", "birth_date_display", "death_legacy_date",
    "death_sort_date_key", "death_date_display", "living_flag", "private_flag"
  ];

  const COMPACT_PERSON_COLUMNS = [
    "dataset_id", "individual_id", "legacy_id", "prefix", "given_name", "surname",
    "title", "gender", "birth_date", "birth_sort_date", "death_date",
    "death_sort_date", "living", "private"
  ].join(", ");

  const BY_ID = Object.freeze({
    events: ["events", "event_id"],
    eventTypes: ["event_types", "event_type_id"],
    locations: ["locations", "location_id"],
    sources: ["sources", "source_id"],
    stories: ["stories", "story_id"],
    people: ["individuals", "individual_id"]
  });

  function jsonValue(value) {
    if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return value;
    }
    if (typeof value === "bigint") return String(value);
    if (value instanceof Uint8Array) return new TextDecoder("utf-8").decode(value);
    if (ArrayBuffer.isView(value)) {
      return new TextDecoder("utf-8").decode(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
    }
    return String(value);
  }

  function queryAll(target, sql, parameters = []) {
    const statement = target.prepare(sql);
    try {
      if (parameters.length) statement.bind(parameters);
      const rows = [];
      while (statement.step()) {
        const raw = statement.getAsObject();
        const row = {};
        Object.keys(raw).forEach((name) => {
          row[name] = jsonValue(raw[name]);
        });
        rows.push(row);
      }
      return rows;
    } finally {
      statement.free();
    }
  }

  function all(sql, parameters = []) {
    return queryAll(database, sql, parameters);
  }

  function one(sql, parameters = []) {
    return all(sql, parameters)[0] || null;
  }

  function scalar(sql, parameters = []) {
    const row = one(sql, parameters);
    return row ? row[Object.keys(row)[0]] : null;
  }

  function placeholders(values) {
    return values.map(() => "?").join(", ");
  }

  function rowsByIds(kind, values, datasetId) {
    const definition = BY_ID[kind];
    const ids = Array.from(values).filter((value) => value !== null && value !== undefined);
    if (!definition || !ids.length) return [];
    const [table, idColumn] = definition;
    return all(
      `SELECT * FROM ${table} WHERE dataset_id = ? AND ${idColumn} IN (${placeholders(ids)})`,
      [datasetId, ...ids]
    );
  }

  function uniqueRows(rows) {
    const result = [];
    const seen = new Set();
    rows.forEach((row) => {
      const marker = JSON.stringify(row);
      if (!seen.has(marker)) {
        seen.add(marker);
        result.push(row);
      }
    });
    return result;
  }

  function decodeLegacyDate(value) {
    if (value === null || value === undefined) return null;
    const text = String(value).trim();
    if (!text || text === "0" || text === "-99999999" || text === "99999999") return null;

    let match = /^(\d{2})(\d{2})(\d{2})(\d{4})(\d{8})$/.exec(text);
    if (match) {
      if (!["00", "10"].includes(match[1]) || match[5] !== "00000000") return text;
      const display = formatDateParts(Number(match[4]), Number(match[3]), Number(match[2]), text);
      return match[1] === "10" ? `about ${display}` : display;
    }
    match = /^(\d{4})(\d{2})(\d{2})$/.exec(text);
    if (match) return formatDateParts(Number(match[1]), Number(match[2]), Number(match[3]), text);
    return text;
  }

  function formatDateParts(year, month, day, original) {
    if (year < 1 || year > 9999) return original;
    const yearText = String(year).padStart(4, "0");
    if (month === 0 && day === 0) return yearText;
    if (month >= 1 && month <= 12 && day === 0) {
      return `${yearText}-${String(month).padStart(2, "0")}`;
    }
    const monthLengths = [31, ((year % 4 === 0 && year % 100 !== 0) || year % 400 === 0) ? 29 : 28,
      31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (month < 1 || month > 12 || day < 1 || day > monthLengths[month - 1]) return original;
    return `${yearText}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  function normalizePerson(row) {
    const person = { ...row };
    Object.keys(PERSON_ALIASES).forEach((alias) => {
      const source = PERSON_ALIASES[alias];
      if (!(alias in person) && source in person) person[alias] = person[source];
    });
    Object.keys(person).forEach((name) => {
      if (name.endsWith("_date") && !name.endsWith("_sort_date")) {
        person[`${name}_display`] = decodeLegacyDate(person[name]);
      }
    });
    person.birth_date_display = decodeLegacyDate(person.birth_legacy_date);
    person.death_date_display = decodeLegacyDate(person.death_legacy_date);
    const name = [person.title_prefix, person.given_names, person.surname, person.title_suffix]
      .map((part) => String(part || "").trim())
      .filter(Boolean)
      .join(" ");
    person.display_name = name || `Person ${person.person_id === undefined ? "" : person.person_id}`.trim();
    return person;
  }

  function personReference(person) {
    const normalized = normalizePerson(person);
    const result = {};
    PERSON_REFERENCE_FIELDS.forEach((name) => {
      if (name in normalized) result[name] = normalized[name];
    });
    return result;
  }

  function withRelationship(person, relationship, marriageId) {
    const result = personReference(person);
    result.relationship = relationship;
    if (marriageId !== null && marriageId !== undefined) result.through_marriage_id = marriageId;
    return result;
  }

  function idKey(value) {
    return String(value);
  }

  function addAliasesToMarriage(row) {
    const marriage = { ...row };
    marriage.husband_person_id = marriage.husband_individual_id;
    marriage.wife_person_id = marriage.wife_individual_id;
    return marriage;
  }

  function addAliasesToChild(row) {
    const child = { ...row };
    child.parent_marriage_id = child.marriage_id;
    child.child_person_id = child.individual_id;
    child.child_order = child.display_order;
    return child;
  }

  function parseInteger(value, label, fallback) {
    const text = value === null ? null : String(value);
    if ((text === null || text === "") && fallback !== undefined) return fallback;
    if (text === null || !/^-?\d+$/.test(text)) throw new Error(`Invalid ${label}`);
    const parsed = Number(text);
    if (!Number.isSafeInteger(parsed)) throw new Error(`Invalid ${label}`);
    return parsed;
  }

  function parseIdentifier(value, label) {
    if (value === null || value === undefined || String(value) === "") throw new Error(`${label} is required`);
    const text = String(value);
    if (/^-?\d+$/.test(text)) {
      const parsed = Number(text);
      if (Number.isSafeInteger(parsed)) return parsed;
    }
    return text;
  }

  function bounded(value, label, fallback, minimum, maximum) {
    return Math.max(minimum, Math.min(parseInteger(value, label, fallback), maximum));
  }

  function firstParameter(parameters, name) {
    return parameters.has(name) ? parameters.get(name) : null;
  }

  function getPerson(datasetId, personId) {
    const row = one(
      "SELECT * FROM individuals WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, personId]
    );
    return row ? normalizePerson(row) : null;
  }

  function listDatasets() {
    return all("SELECT * FROM datasets ORDER BY id").map((row) => {
      if (!("dataset_id" in row)) row.dataset_id = row.id;
      return row;
    });
  }

  function listPeople(parameters) {
    const datasetId = parseIdentifier(firstParameter(parameters, "dataset_id"), "dataset_id");
    const limit = bounded(firstParameter(parameters, "limit"), "limit", 100, 1, 500);
    const offset = bounded(firstParameter(parameters, "offset"), "offset", 0, 0, Number.MAX_SAFE_INTEGER);
    const total = Number(scalar("SELECT count(*) FROM individuals WHERE dataset_id = ?", [datasetId]) || 0);
    const people = all(
      `SELECT ${COMPACT_PERSON_COLUMNS} FROM individuals p WHERE dataset_id = ?
       ORDER BY CASE WHEN surname IS NULL OR surname = '' THEN 1 ELSE 0 END,
                surname COLLATE NOCASE,
                CASE WHEN given_name IS NULL OR given_name = '' THEN 1 ELSE 0 END,
                given_name COLLATE NOCASE, individual_id
       LIMIT ? OFFSET ?`,
      [datasetId, limit, offset]
    ).map(normalizePerson);
    return { people, total, limit, offset, has_more: offset + people.length < total };
  }

  function likeTerm(token) {
    return `%${token.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_")}%`;
  }

  function searchPeople(parameters) {
    const datasetId = parseIdentifier(firstParameter(parameters, "dataset_id"), "dataset_id");
    const query = firstParameter(parameters, "q");
    if (query === null) throw new Error("q is required");
    const limit = bounded(firstParameter(parameters, "limit"), "limit", 50, 1, 500);
    const terms = String(query).trim().split(/\s+/).filter(Boolean).map(likeTerm);
    if (!terms.length) return [];

    const primaryName = "COALESCE(CAST(p.prefix AS TEXT), '') || ' ' || " +
      "COALESCE(CAST(p.given_name AS TEXT), '') || ' ' || " +
      "COALESCE(CAST(p.surname AS TEXT), '') || ' ' || COALESCE(CAST(p.title AS TEXT), '')";
    const alternateName = "COALESCE(CAST(a.prefix AS TEXT), '') || ' ' || " +
      "COALESCE(CAST(a.given_name AS TEXT), '') || ' ' || " +
      "COALESCE(CAST(a.surname AS TEXT), '') || ' ' || COALESCE(CAST(a.title AS TEXT), '')";
    const clauses = [];
    const values = [datasetId];
    terms.forEach((term) => {
      clauses.push(`((${primaryName}) LIKE ? ESCAPE '\\' COLLATE NOCASE OR EXISTS (
        SELECT 1 FROM alternate_names a
        WHERE a.dataset_id = p.dataset_id AND a.individual_id = p.individual_id
          AND (${alternateName}) LIKE ? ESCAPE '\\' COLLATE NOCASE
      ))`);
      values.push(term, term);
    });
    const normalizedQuery = String(query).trim().replace(/\s+/g, " ");
    const prefixTerm = `${normalizedQuery.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_")}%`;
    const primaryTerms = terms
      .map(() => `(${primaryName}) LIKE ? ESCAPE '\\' COLLATE NOCASE`)
      .join(" AND ");
    values.push(
      normalizedQuery,
      normalizedQuery,
      normalizedQuery,
      normalizedQuery,
      prefixTerm,
      prefixTerm,
      ...terms
    );
    values.push(limit);
    return all(
      `SELECT ${COMPACT_PERSON_COLUMNS} FROM individuals p
       WHERE p.dataset_id = ? AND ${clauses.join(" AND ")}
       ORDER BY CASE
                  WHEN trim(COALESCE(p.given_name, '') || ' ' || COALESCE(p.surname, '')) = ? COLLATE NOCASE
                    OR trim(COALESCE(p.surname, '') || ' ' || COALESCE(p.given_name, '')) = ? COLLATE NOCASE THEN 0
                  WHEN COALESCE(p.given_name, '') = ? COLLATE NOCASE
                    OR COALESCE(p.surname, '') = ? COLLATE NOCASE THEN 1
                  WHEN trim(COALESCE(p.given_name, '') || ' ' || COALESCE(p.surname, '')) LIKE ? ESCAPE '\\' COLLATE NOCASE
                    OR trim(COALESCE(p.surname, '') || ' ' || COALESCE(p.given_name, '')) LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 2
                  WHEN ${primaryTerms} THEN 3
                  ELSE 4
                END,
                CASE WHEN p.surname IS NULL OR p.surname = '' THEN 1 ELSE 0 END,
                 p.surname COLLATE NOCASE,
                CASE WHEN p.given_name IS NULL OR p.given_name = '' THEN 1 ELSE 0 END,
                p.given_name COLLATE NOCASE, p.individual_id
       LIMIT ?`,
      values
    ).map(normalizePerson);
  }

  function getFamily(datasetId, personId) {
    const person = getPerson(datasetId, personId);
    if (!person) return null;
    const actualId = person.person_id;
    const marriages = all(
      "SELECT * FROM marriages WHERE dataset_id = ? AND (husband_individual_id = ? OR wife_individual_id = ?)",
      [datasetId, actualId, actualId]
    ).map(addAliasesToMarriage);
    const parentLinks = all(
      "SELECT * FROM children WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, actualId]
    ).map(addAliasesToChild);
    const parentMarriageIds = new Set(parentLinks.map((row) => row.parent_marriage_id));
    const parentMarriages = parentMarriageIds.size
      ? all(
        `SELECT * FROM marriages WHERE dataset_id = ? AND marriage_id IN (${placeholders(Array.from(parentMarriageIds))})`,
        [datasetId, ...parentMarriageIds]
      ).map(addAliasesToMarriage)
      : [];
    const ownMarriageIds = new Set(marriages.map((row) => row.marriage_id));
    const childLinks = ownMarriageIds.size
      ? all(
        `SELECT * FROM children WHERE dataset_id = ? AND marriage_id IN (${placeholders(Array.from(ownMarriageIds))})`,
        [datasetId, ...ownMarriageIds]
      ).map(addAliasesToChild)
      : [];
    const siblingLinks = parentMarriageIds.size
      ? all(
        `SELECT * FROM children WHERE dataset_id = ? AND marriage_id IN (${placeholders(Array.from(parentMarriageIds))}) AND individual_id <> ?`,
        [datasetId, ...parentMarriageIds, actualId]
      ).map(addAliasesToChild)
      : [];

    const relatedIds = new Set();
    parentMarriages.forEach((row) => {
      relatedIds.add(row.husband_person_id);
      relatedIds.add(row.wife_person_id);
    });
    marriages.forEach((row) => {
      relatedIds.add(row.husband_person_id === actualId ? row.wife_person_id : row.husband_person_id);
    });
    childLinks.forEach((row) => relatedIds.add(row.child_person_id));
    siblingLinks.forEach((row) => relatedIds.add(row.child_person_id));
    relatedIds.delete(null);
    relatedIds.delete(undefined);
    const people = new Map(rowsByIds("people", relatedIds, datasetId).map((row) => [idKey(row.individual_id), normalizePerson(row)]));

    function uniquePeople(rows) {
      const seen = new Set();
      return rows.filter((row) => {
        if (!row || seen.has(idKey(row.person_id))) return false;
        seen.add(idKey(row.person_id));
        return true;
      });
    }

    const parents = [];
    parentMarriages.forEach((marriage) => {
      [marriage.husband_person_id, marriage.wife_person_id].forEach((id) => {
        const relative = people.get(idKey(id));
        if (relative) parents.push(withRelationship(relative, "parent", marriage.marriage_id));
      });
    });
    const spouses = [];
    marriages.forEach((marriage) => {
      const spouseId = marriage.husband_person_id === actualId
        ? marriage.wife_person_id : marriage.husband_person_id;
      const spouse = people.get(idKey(spouseId));
      if (spouse) spouses.push(withRelationship(spouse, "spouse", marriage.marriage_id));
    });
    const children = childLinks.map((link) => {
      const child = people.get(idKey(link.child_person_id));
      return child ? withRelationship(child, "child", link.parent_marriage_id) : null;
    }).filter(Boolean);
    const siblings = siblingLinks.map((link) => {
      const sibling = people.get(idKey(link.child_person_id));
      return sibling ? withRelationship(sibling, "sibling", link.parent_marriage_id) : null;
    }).filter(Boolean);
    return {
      person: personReference(person),
      parents: uniquePeople(parents),
      spouses: uniquePeople(spouses),
      children: uniquePeople(children),
      siblings: uniquePeople(siblings),
      marriages
    };
  }

  function getPersonFacts(datasetId, personId) {
    const person = getPerson(datasetId, personId);
    if (!person) return null;
    const actualId = person.person_id;
    const alternateNames = all(
      "SELECT * FROM alternate_names WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, actualId]
    );
    const participants = all(
      "SELECT * FROM event_participants WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, actualId]
    );
    const participantEventIds = new Set(participants.map((row) => row.event_id));
    const sharedEvents = rowsByIds("events", participantEventIds, datasetId);
    const directEvents = person.legacy_rin === null || person.legacy_rin === undefined
      ? []
      : all(
        "SELECT * FROM events WHERE dataset_id = ? AND record_type = 0 AND owner_record_id = ?",
        [datasetId, person.legacy_rin]
      );
    const events = uniqueRows([...sharedEvents, ...directEvents]);
    const eventIds = new Set(events.map((row) => row.event_id));
    const eventTypes = rowsByIds(
      "eventTypes",
      new Set(events.map((row) => row.event_type_id)),
      datasetId
    );
    const eventLocationIds = new Set(events.map((row) => row.event_location_id));
    const eventLocations = rowsByIds("locations", eventLocationIds, datasetId);
    const typeById = new Map(eventTypes.map((row) => [idKey(row.event_type_id), row]));
    const locationById = new Map(eventLocations.map((row) => [idKey(row.location_id), row]));
    const participantsByEvent = new Map();
    participants.forEach((participant) => {
      const key = idKey(participant.event_id);
      if (!participantsByEvent.has(key)) participantsByEvent.set(key, []);
      participantsByEvent.get(key).push(participant);
    });
    const enrichedEvents = events.map((row) => {
      const event = { ...row, event_date_display: decodeLegacyDate(row.event_date) };
      event.participants = participantsByEvent.get(idKey(row.event_id)) || [];
      const eventType = typeById.get(idKey(row.event_type_id));
      if (eventType) {
        event.event_type = eventType;
        event.event_type_name = eventType.event_type ?? eventType.event_type_name ?? eventType.name ?? eventType.title;
      }
      const location = locationById.get(idKey(row.event_location_id));
      if (location) {
        event.location = location;
        event.location_name = location.location ?? location.location_name ?? location.name ?? location.place;
      }
      return event;
    });

    const childLinks = all(
      "SELECT * FROM children WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, actualId]
    );
    const marriages = all(
      "SELECT * FROM marriages WHERE dataset_id = ? AND (husband_individual_id = ? OR wife_individual_id = ?)",
      [datasetId, actualId, actualId]
    );
    const storyLinks = all(
      "SELECT * FROM story_individuals WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, actualId]
    );
    const todos = all(
      "SELECT * FROM todos WHERE dataset_id = ? AND individual_id = ?",
      [datasetId, actualId]
    );
    const stories = rowsByIds("stories", new Set(storyLinks.map((row) => row.story_id)), datasetId);

    const citationGroups = [
      [[0, 1, 2, 3, 4, 5, 15, 16, 26, 27], [actualId]],
      [[10], alternateNames.map((row) => row.alternate_name_id)],
      [[12, 13], todos.map((row) => row.todo_id)],
      [[17], childLinks.map((row) => row.child_id)],
      [[18, 20], marriages.map((row) => row.marriage_id)],
      [[28], stories.map((row) => row.story_id)],
      [[30], Array.from(eventIds)],
      [[31], participants.map((row) => row.event_participant_id)]
    ];
    const citationClauses = [];
    const citationValues = [datasetId];
    citationGroups.forEach(([types, recordIds]) => {
      const ids = recordIds.filter((value) => value !== null && value !== undefined);
      if (!ids.length) return;
      citationClauses.push(
        `(type IN (${placeholders(types)}) AND cited_record_id IN (${placeholders(ids)}))`
      );
      citationValues.push(...types, ...ids);
    });
    const citations = citationClauses.length
      ? all(
        `SELECT * FROM citations WHERE dataset_id = ? AND (${citationClauses.join(" OR ")})`,
        citationValues
      )
      : [];
    const sources = rowsByIds("sources", new Set(citations.map((row) => row.source_id)), datasetId);

    const mediaClauses = ["(record_type IN (0, 1, 2, 3, 4) AND owner_record_id = ?)"];
    const mediaValues = [datasetId, actualId];
    const mediaGroups = [
      [20, marriages.map((row) => row.marriage_id)],
      [30, Array.from(eventIds)],
      [40, sources.map((row) => row.source_id)],
      [41, citations.map((row) => row.citation_id)],
      [70, todos.map((row) => row.todo_id)]
    ];
    mediaGroups.forEach(([type, recordIds]) => {
      const ids = recordIds.filter((value) => value !== null && value !== undefined);
      if (!ids.length) return;
      mediaClauses.push(`(record_type = ? AND owner_record_id IN (${placeholders(ids)}))`);
      mediaValues.push(type, ...ids);
    });
    const media = all(
      `SELECT * FROM media WHERE dataset_id = ? AND (${mediaClauses.join(" OR ")})`,
      mediaValues
    );

    const locationIds = new Set(eventLocationIds);
    Object.keys(person).forEach((name) => {
      if (name.endsWith("_location_id")) locationIds.add(person[name]);
    });
    stories.forEach((story) => locationIds.add(story.story_location_id));
    marriages.forEach((marriage) => locationIds.add(marriage.marriage_location_id));
    locationIds.delete(null);
    locationIds.delete(undefined);
    const locations = rowsByIds("locations", locationIds, datasetId);

    const identity = {};
    [
      "dataset_id", "person_id", "legacy_rin", "title_prefix", "given_names", "surname",
      "title_suffix", "gender_code", "birth_legacy_date", "birth_sort_date_key",
      "death_legacy_date", "death_sort_date_key", "living_flag", "private_flag"
    ].forEach((name) => {
      if (name in person) identity[name] = person[name];
    });
    const notes = {};
    Object.keys(person).forEach((name) => {
      if (name.endsWith("_note") || name.endsWith("_notes")) notes[name] = person[name];
    });
    ["general_notes", "research_notes", "medical_notes", "cause_of_death"].forEach((name) => {
      if (name in person) notes[name] = person[name];
    });
    return {
      person,
      identity,
      notes,
      alternate_names: alternateNames,
      events: enrichedEvents,
      locations,
      citations,
      sources,
      media,
      stories,
      todo: todos
    };
  }

  function loadFamilyGraph(datasetId) {
    const people = new Map();
    all("SELECT * FROM individuals WHERE dataset_id = ?", [datasetId]).forEach((row) => {
      const person = normalizePerson(row);
      people.set(idKey(person.person_id), person);
    });
    const marriages = all("SELECT * FROM marriages WHERE dataset_id = ?", [datasetId])
      .map(addAliasesToMarriage);
    const children = all("SELECT * FROM children WHERE dataset_id = ?", [datasetId])
      .map(addAliasesToChild);
    return { people, marriages, children };
  }

  function addEdge(graph, from, to, relationship, marriageId) {
    const key = idKey(from);
    if (!graph.has(key)) graph.set(key, []);
    graph.get(key).push({ target: idKey(to), relationship, marriageId });
  }

  function buildGraph(data, includeSpouses) {
    const graph = new Map();
    const marriageById = new Map(data.marriages.map((row) => [idKey(row.marriage_id), row]));
    data.children.forEach((link) => {
      const marriage = marriageById.get(idKey(link.parent_marriage_id));
      const childKey = idKey(link.child_person_id);
      if (!marriage || !data.people.has(childKey)) return;
      [marriage.husband_person_id, marriage.wife_person_id].forEach((parentId) => {
        const parentKey = idKey(parentId);
        if (!data.people.has(parentKey)) return;
        addEdge(graph, childKey, parentKey, "parent", marriage.marriage_id);
        addEdge(graph, parentKey, childKey, "child", marriage.marriage_id);
      });
    });
    if (includeSpouses) {
      data.marriages.forEach((marriage) => {
        const husband = idKey(marriage.husband_person_id);
        const wife = idKey(marriage.wife_person_id);
        if (husband === wife || !data.people.has(husband) || !data.people.has(wife)) return;
        addEdge(graph, husband, wife, "spouse", marriage.marriage_id);
        addEdge(graph, wife, husband, "spouse", marriage.marriage_id);
      });
    }
    return graph;
  }

  function specificRelationship(base, target) {
    const gender = String(target.gender_code ?? "").trim().toLowerCase();
    const male = gender === "0" || gender === "m" || gender === "male";
    const female = gender === "1" || gender === "f" || gender === "female";
    if (base === "parent") return male ? "father" : female ? "mother" : "parent";
    if (base === "child") return male ? "son" : female ? "daughter" : "child";
    if (base === "spouse") return male ? "husband" : female ? "wife" : "spouse";
    return base;
  }

  function getTree(datasetId, personId, direction, maxDepth) {
    if (direction !== "ancestors" && direction !== "descendants") {
      throw new Error("direction must be ancestors or descendants");
    }
    const data = loadFamilyGraph(datasetId);
    const rootKey = idKey(personId);
    if (!data.people.has(rootKey)) return null;
    const graph = buildGraph(data, false);
    const wanted = direction === "ancestors" ? "parent" : "child";
    const queue = [[rootKey, 0]];
    const visited = new Set([rootKey]);
    const traversed = [];
    const links = [];
    const generations = new Map();
    for (let index = 0; index < queue.length; index += 1) {
      const [current, depth] = queue[index];
      if (depth >= maxDepth) continue;
      (graph.get(current) || []).forEach((edge) => {
        if (edge.relationship !== wanted) return;
        const target = data.people.get(edge.target);
        const relationship = specificRelationship(edge.relationship, target);
        links.push({
          from_person_id: data.people.get(current).person_id,
          to_person_id: target.person_id,
          relationship,
          marriage_id: edge.marriageId
        });
        if (visited.has(edge.target)) return;
        visited.add(edge.target);
        const item = personReference(target);
        item.depth = depth + 1;
        item.relationship = relationship;
        traversed.push(item);
        if (!generations.has(depth + 1)) generations.set(depth + 1, []);
        generations.get(depth + 1).push(item);
        queue.push([edge.target, depth + 1]);
      });
    }
    return {
      root: personReference(data.people.get(rootKey)),
      direction,
      max_depth: maxDepth,
      people: traversed,
      generations: Array.from(generations).sort((left, right) => left[0] - right[0])
        .map(([depth, people]) => ({ depth, people })),
      links
    };
  }

function asPersonId(key) {
    return /^-?\d+$/.test(String(key)) ? Number(key) : key;
  }

  function getFullTree(datasetId, firstPersonId, secondPersonId, maxDepth) {
    const data = loadFamilyGraph(datasetId);
    const firstKey = idKey(firstPersonId);
    const secondKey = secondPersonId === null || secondPersonId === undefined ? null : idKey(secondPersonId);
    const rootIds = [firstKey];
    if (secondKey !== null) rootIds.push(secondKey);
    if (!rootIds.every((key) => data.people.has(key)) || (secondKey !== null && firstKey === secondKey)) return null;

    const people = new Map();
    function includePerson(candidate) {
      const key = idKey(candidate);
      if (!data.people.has(key)) return null;
      people.set(key, personReference(data.people.get(key)));
      return key;
    }
    rootIds.forEach((key) => includePerson(key));

    const marriagesByPerson = new Map();
    data.marriages.forEach((marriage) => {
      [marriage.husband_person_id, marriage.wife_person_id].forEach((id) => {
        if (id === null || id === undefined || !data.people.has(idKey(id))) return;
        const key = idKey(id);
        if (!marriagesByPerson.has(key)) marriagesByPerson.set(key, []);
        marriagesByPerson.get(key).push(marriage);
      });
    });

    let sharedMarriage = null;
    if (secondKey !== null) {
      sharedMarriage = (marriagesByPerson.get(firstKey) || []).find((marriage) => {
        const partners = new Set(
          [marriage.husband_person_id, marriage.wife_person_id]
            .filter((id) => id !== null && id !== undefined)
            .map(idKey)
        );
        return partners.has(firstKey) && partners.has(secondKey);
      }) || null;
    }

    const rootReferences = rootIds.map((key) => personReference(data.people.get(key)));
    if (secondKey !== null && !sharedMarriage) {
      const parentLinks = all(
        `SELECT * FROM children WHERE dataset_id = ? AND individual_id IN (${placeholders(rootIds)})`,
        [datasetId, ...rootIds]
      ).map(addAliasesToChild);
      const rootsWithParents = new Set(parentLinks.map((link) => idKey(link.child_person_id)));
      return {
        status: "no_shared_couple",
        message: "The requested people do not share a recorded marriage in this dataset.",
        dataset_id: datasetId,
        max_depth: maxDepth,
        truncated: rootsWithParents.size > 0,
        roots: rootReferences,
        people: rootReferences,
        couples: [],
        links: [],
        has_parents: rootIds.filter((key) => rootsWithParents.has(key)).map(asPersonId),
        counts: { people: rootReferences.length, couples: 0, links: 0, generations: 1 }
      };
    }

    const syntheticRoot = secondKey === null
      ? {
        dataset_id: datasetId,
        marriage_id: `root:${firstKey}`,
        husband_person_id: asPersonId(firstKey),
        wife_person_id: null
      }
      : null;
    const coupleEntries = new Map();
    (secondKey === null ? [syntheticRoot] : [sharedMarriage]).forEach((marriage) => {
      coupleEntries.set(idKey(marriage.marriage_id), { marriage, depth: 0, rootCouple: true });
    });

    const ancestorDepths = new Map();
    rootIds.forEach((key) => ancestorDepths.set(key, 0));
    const frontier = [...rootIds];
    const expanded = new Set();
    const hasParents = new Set();
    const links = [];
    const seenLinks = new Set();
    let truncated = false;

    for (let depth = 0; depth <= maxDepth; depth += 1) {
      const current = frontier.filter((key) => !expanded.has(key));
      if (!current.length) break;
      current.forEach((key) => expanded.add(key));
      const parentLinks = all(
        `SELECT * FROM children WHERE dataset_id = ? AND individual_id IN (${placeholders(current)})`,
        [datasetId, ...current]
      ).map(addAliasesToChild);
      const currentSet = new Set(current);
      parentLinks.forEach((link) => {
        if (currentSet.has(idKey(link.child_person_id))) hasParents.add(idKey(link.child_person_id));
      });
      if (depth === maxDepth) {
        truncated = parentLinks.length > 0;
        break;
      }
      const linksByChild = new Map();
      parentLinks.forEach((link) => {
        const childKey = idKey(link.child_person_id);
        if (!linksByChild.has(childKey)) linksByChild.set(childKey, []);
        linksByChild.get(childKey).push(link);
      });
      const marriageIds = [...new Set(parentLinks.map((link) => idKey(link.parent_marriage_id)))];
      const marriagesById = new Map(
        all(
          `SELECT * FROM marriages WHERE dataset_id = ? AND marriage_id IN (${placeholders(marriageIds)})`,
          [datasetId, ...marriageIds]
        ).map(addAliasesToMarriage).map((marriage) => [idKey(marriage.marriage_id), marriage])
      );
      const candidateParentIds = [];
      const orderedCurrent = current.slice().sort(
        (left, right) => Number(left) - Number(right) || left.localeCompare(right)
      );
      orderedCurrent.forEach((childKey) => {
        (linksByChild.get(childKey) || []).forEach((link) => {
          const marriageId = idKey(link.parent_marriage_id);
          const marriage = marriagesById.get(marriageId);
          if (!marriage) return;
          const partnerIds = [marriage.husband_person_id, marriage.wife_person_id]
            .filter((id) => id !== null && id !== undefined)
            .map(idKey);
          if (partnerIds.some((partnerKey) => (
            partnerKey === childKey
            || (ancestorDepths.has(partnerKey) && ancestorDepths.get(partnerKey) <= depth)
          ))) return;
          const existing = coupleEntries.get(marriageId);
          if (existing && existing.depth <= depth) return;
          if (!existing) coupleEntries.set(marriageId, { marriage, depth: depth + 1, rootCouple: false });
          const linkKey = `${childKey}\u0000${marriageId}`;
          if (!seenLinks.has(linkKey)) {
            seenLinks.add(linkKey);
            links.push({
              child_person_id: asPersonId(childKey),
              parent_couple_id: marriage.marriage_id,
              depth: depth + 1
            });
          }
          candidateParentIds.push(...partnerIds);
        });
      });
      candidateParentIds.forEach((key) => includePerson(key));
      const nextFrontier = [];
      candidateParentIds.slice().sort().forEach((key) => {
        if (!data.people.has(key)) return;
        if (!ancestorDepths.has(key)) {
          ancestorDepths.set(key, depth + 1);
          nextFrontier.push(key);
        }
      });
      frontier.splice(0, frontier.length, ...nextFrontier);
    }

    const orderedCouples = [...coupleEntries.values()].sort(
      (left, right) => left.depth - right.depth
        || Number(left.marriage.marriage_id) - Number(right.marriage.marriage_id)
    );

    const recordedMarriageIds = orderedCouples
      .filter((entry) => String(entry.marriage.marriage_id) !== `root:${firstKey}`)
      .map((entry) => entry.marriage.marriage_id);
    const childLinksByMarriage = new Map();
    if (recordedMarriageIds.length) {
      all(
        `SELECT * FROM children WHERE dataset_id = ? AND marriage_id IN (${placeholders(recordedMarriageIds)})`,
        [datasetId, ...recordedMarriageIds]
      ).map(addAliasesToChild).forEach((link) => {
        const key = idKey(link.parent_marriage_id);
        if (!childLinksByMarriage.has(key)) childLinksByMarriage.set(key, []);
        childLinksByMarriage.get(key).push(link);
      });
    }
    childLinksByMarriage.forEach((rows) => rows.sort(
      (left, right) => Number(left.child_order ?? 0) - Number(right.child_order ?? 0)
    ));

    const alternativesByCouple = new Map();
    orderedCouples.forEach((entry) => {
      const coupleId = idKey(entry.marriage.marriage_id);
      const partnerIds = [entry.marriage.husband_person_id, entry.marriage.wife_person_id]
        .filter((id) => id !== null && id !== undefined)
        .map(idKey);
      const alternatives = [];
      partnerIds.forEach((partnerKey) => {
        (marriagesByPerson.get(partnerKey) || []).forEach((alternate) => {
          if (idKey(alternate.marriage_id) === coupleId) return;
          const partnerId = asPersonId(partnerKey);
          const spouseId = alternate.husband_person_id === partnerId
            ? alternate.wife_person_id
            : alternate.husband_person_id;
          if (spouseId === null || spouseId === undefined || !data.people.has(idKey(spouseId))) return;
          includePerson(spouseId);
          alternatives.push({
            partner_person_id: partnerId,
            marriage_id: alternate.marriage_id,
            spouse_person_id: spouseId,
            spouse: personReference(data.people.get(idKey(spouseId)))
          });
        });
      });
      alternatives.sort((left, right) => (
        partnerIds.indexOf(idKey(left.partner_person_id)) - partnerIds.indexOf(idKey(right.partner_person_id))
      ));
      alternativesByCouple.set(coupleId, alternatives);
    });

    const couples = [];
    orderedCouples.forEach((entry) => {
      const marriage = entry.marriage;
      const coupleId = idKey(marriage.marriage_id);
      const partnerIds = [marriage.husband_person_id, marriage.wife_person_id]
        .filter((id) => id !== null && id !== undefined)
        .map(idKey);
      const childIds = (childLinksByMarriage.get(coupleId) || [])
        .map((link) => asPersonId(link.child_person_id));
      childIds.forEach((childId) => includePerson(childId));
      const couple = {
        dataset_id: marriage.dataset_id,
        marriage_id: marriage.marriage_id,
        depth: entry.depth,
        root_couple: entry.rootCouple,
        partner_person_ids: partnerIds.map(asPersonId),
        partners: partnerIds.map((key) => personReference(data.people.get(key))),
        child_ids: childIds,
        children: childIds.map((childId) => personReference(data.people.get(idKey(childId)))),
        alternative_spouses: alternativesByCouple.get(coupleId) || []
      };
      if (marriage.marriage_date !== undefined && marriage.marriage_date !== null) {
        couple.marriage_date = marriage.marriage_date;
        couple.marriage_date_display = decodeLegacyDate(marriage.marriage_date);
      }
      if (marriage.private_flag !== undefined) couple.private_flag = marriage.private_flag;
      couples.push(couple);
    });

    const visibleKeys = [...ancestorDepths.keys()]
      .filter((key) => people.has(key))
      .sort(
        (left, right) => ancestorDepths.get(left) - ancestorDepths.get(right)
          || Number(left) - Number(right)
      );
    const personItems = [];
    visibleKeys.forEach((key) => {
      const reference = people.get(key);
      reference.depth = ancestorDepths.get(key);
      personItems.push(reference);
    });
    const menuKeys = [...people.keys()]
      .filter((key) => !ancestorDepths.has(key))
      .sort((left, right) => Number(left) - Number(right));
    menuKeys.forEach((key) => personItems.push(people.get(key)));

    links.sort(
      (left, right) => left.depth - right.depth
        || Number(left.parent_couple_id) - Number(right.parent_couple_id)
        || Number(left.child_person_id) - Number(right.child_person_id)
    );
    const hasParentsList = [...hasParents].map(asPersonId).sort((left, right) => left - right);
    return {
      status: "ok",
      message: null,
      dataset_id: datasetId,
      max_depth: maxDepth,
      truncated,
      roots: rootReferences,
      people: personItems,
      couples,
      links,
      has_parents: hasParentsList,
      counts: {
        people: personItems.length,
        couples: couples.length,
        links: links.length,
        generations: new Set([0, ...couples.map((couple) => couple.depth)]).size
      }
    };
  }

  function shortestRelationship(datasetId, fromPersonId, toPersonId) {
    const data = loadFamilyGraph(datasetId);
    const start = idKey(fromPersonId);
    const goal = idKey(toPersonId);
    if (!data.people.has(start) || !data.people.has(goal)) {
      return {
        found: false,
        reason: `${data.people.has(start) ? "to" : "from"} person was not found`,
        steps: []
      };
    }
    if (start === goal) {
      return {
        found: true,
        length: 0,
        people: [personReference(data.people.get(start))],
        steps: [],
        explanation: "Both identifiers refer to the same person."
      };
    }
    const graph = buildGraph(data, true);
    const queue = [start];
    const visited = new Set([start]);
    const previous = new Map();
    for (let index = 0; index < queue.length && !visited.has(goal); index += 1) {
      const current = queue[index];
      for (const edge of graph.get(current) || []) {
        if (visited.has(edge.target)) continue;
        visited.add(edge.target);
        previous.set(edge.target, { from: current, relationship: edge.relationship, marriageId: edge.marriageId });
        queue.push(edge.target);
        if (edge.target === goal) break;
      }
    }
    if (!visited.has(goal)) {
      return { found: false, reason: "No relationship path was found in this dataset.", steps: [] };
    }
    const pathKeys = [goal];
    while (pathKeys[pathKeys.length - 1] !== start) {
      pathKeys.push(previous.get(pathKeys[pathKeys.length - 1]).from);
    }
    pathKeys.reverse();
    const steps = [];
    const explainedPath = [personReference(data.people.get(start))];
    const explanations = [];
    for (let index = 1; index < pathKeys.length; index += 1) {
      const currentKey = pathKeys[index - 1];
      const targetKey = pathKeys[index];
      const edge = previous.get(targetKey);
      const current = data.people.get(currentKey);
      const target = data.people.get(targetKey);
      const relationship = specificRelationship(edge.relationship, target);
      const description = `${target.display_name} is the ${relationship} of ${current.display_name}.`;
      steps.push({
        from_person_id: current.person_id,
        to_person_id: target.person_id,
        relationship,
        marriage_id: edge.marriageId,
        description
      });
      const pathPerson = personReference(target);
      pathPerson.relationship = relationship;
      explainedPath.push(pathPerson);
      explanations.push(description);
    }
    return {
      found: true,
      length: steps.length,
      people: pathKeys.map((key) => personReference(data.people.get(key))),
      path: explainedPath,
      steps,
      explanation: explanations.join(" ")
    };
  }

  function parseRequest(path) {
    if (typeof path !== "string" || !path.startsWith("/")) throw new Error("Invalid API route");
    let url;
    try {
      url = new URL(path, "http://legacy.local");
    } catch (_) {
      throw new Error("Invalid API route");
    }
    if (!url.pathname.startsWith("/api/")) throw new Error("API route not found");
    return url;
  }

  function personResult(result) {
    if (result === null) throw new Error("Person not found");
    return result;
  }

  async function request(path) {
    if (!database) throw new Error("No database is open");
    const url = parseRequest(path);
    if (url.pathname === "/api/datasets") return listDatasets();
    if (url.pathname === "/api/people") return listPeople(url.searchParams);
    if (url.pathname === "/api/people/search") return searchPeople(url.searchParams);
    if (url.pathname === "/api/full-tree") {
      const datasetId = parseIdentifier(firstParameter(url.searchParams, "dataset"), "dataset");
      const firstId = parseIdentifier(firstParameter(url.searchParams, "first"), "first");
      const secondParameter = firstParameter(url.searchParams, "second");
      const secondId = secondParameter === null ? null : parseIdentifier(secondParameter, "second");
      const generations = bounded(
        firstParameter(url.searchParams, "generations") ?? firstParameter(url.searchParams, "max_depth"),
        "generations",
        3,
        0,
        6
      );
      const result = getFullTree(datasetId, firstId, secondId, generations);
      if (result === null) throw new Error("One or both root people were not found");
      return result;
    }
    if (url.pathname === "/api/relationship") {
      const datasetId = parseIdentifier(firstParameter(url.searchParams, "dataset_id"), "dataset_id");
      const fromId = parseIdentifier(firstParameter(url.searchParams, "from_person_id"), "from_person_id");
      const toId = parseIdentifier(firstParameter(url.searchParams, "to_person_id"), "to_person_id");
      return shortestRelationship(datasetId, fromId, toId);
    }

    const match = /^\/api\/people\/([^/]+)\/([^/]+)(?:\/(facts|family|tree))?$/.exec(url.pathname);
    if (!match) throw new Error("API route not found");
    let datasetText;
    let personText;
    try {
      datasetText = decodeURIComponent(match[1]);
      personText = decodeURIComponent(match[2]);
    } catch (_) {
      throw new Error("Invalid API route");
    }
    const datasetId = parseIdentifier(datasetText, "dataset_id");
    const personId = parseIdentifier(personText, "person_id");
    if (match[3] === "facts") return personResult(getPersonFacts(datasetId, personId));
    if (match[3] === "family") return personResult(getFamily(datasetId, personId));
    if (match[3] === "tree") {
      const direction = firstParameter(url.searchParams, "direction") || "ancestors";
      const generations = bounded(firstParameter(url.searchParams, "generations"), "generations", 4, 0, 10);
      return personResult(getTree(datasetId, personId, direction, generations));
    }
    return personResult(getPerson(datasetId, personId));
  }

  function validateSchema(candidate) {
    const rows = queryAll(
      candidate,
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
      ["datasets", "individuals"]
    );
    const names = new Set(rows.map((row) => row.name));
    if (!names.has("datasets") || !names.has("individuals")) {
      throw new Error("Unsupported database schema: datasets and individuals tables are required");
    }
    try {
      queryAll(candidate, "SELECT id FROM datasets LIMIT 0");
      queryAll(candidate, "SELECT dataset_id, individual_id FROM individuals LIMIT 0");
    } catch (_) {
      throw new Error("Unsupported database schema: required columns are missing");
    }
  }

  async function open(file) {
    if (!file || typeof file.arrayBuffer !== "function") throw new Error("A database file is required");
    if (typeof global.initSqlJs !== "function") throw new Error("SQL.js is not loaded");
    let SQL;
    try {
      SQL = await global.initSqlJs();
    } catch (_) {
      throw new Error("SQL.js could not be initialized");
    }
    let buffer;
    try {
      buffer = await file.arrayBuffer();
    } catch (_) {
      throw new Error("Database file could not be read");
    }
    let candidate;
    try {
      candidate = new SQL.Database(new Uint8Array(buffer));
      validateSchema(candidate);
    } catch (error) {
      if (candidate) candidate.close();
      if (error instanceof Error && error.message.startsWith("Unsupported database schema:")) throw error;
      throw new Error("Invalid SQLite database");
    }
    if (database) database.close();
    database = candidate;
    return {
      name: String(file.name || ""),
      size: Number(file.size ?? buffer.byteLength),
      type: String(file.type || ""),
      lastModified: Number(file.lastModified || 0)
    };
  }

  global.LegacyStandalone = Object.freeze({
    open,
    request,
    get isOpen() {
      return database !== null;
    }
  });
})(window);
