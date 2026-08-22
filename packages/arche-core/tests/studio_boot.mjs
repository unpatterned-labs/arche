// Run the studio's script against a stub DOM and a stub server, and report
// anything it throws.
//
// `tools/arche-studio/index.html` is one file of hand-written HTML and
// JavaScript with no build step, which is deliberate — it is meant to be
// readable top to bottom by somebody who did not write it. The cost is that
// nothing checks it. A syntax error anywhere kills the whole script, so no
// listener is ever registered and every tab and button is inert: the page comes
// up looking frozen rather than broken, and it has done exactly that.
//
// `node --check` catches the syntax case. This catches the next one along: a
// call to something undefined, a reference read before its `const` is
// initialised, a handler that throws while the page is starting up. It is not a
// browser and is not trying to be. It is enough of one that the script runs its
// startup sequence and every tab switch, and says so if anything throws.
//
// Driven from `test_studio_loads.py`, which skips when node is not installed.
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(process.argv[2], "utf8");
const script = /<script>([\s\S]*?)<\/script>/.exec(html)[1];

// Every id the page defines, so $("#x") returns something for all of them.
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));

const errors = [];
const el = (id) => {
  const node = {
    id, value: "", textContent: "", innerHTML: "", hidden: false,
    className: "", title: "", checked: false, files: [], dataset: {},
    style: {}, classList: { add(){}, remove(){}, toggle(){} },
    setAttribute(){}, getAttribute(){ return null; },
    addEventListener(){}, removeEventListener(){}, click(){},
    appendChild(){}, remove(){}, focus(){},
    querySelector(){ return el("stub"); },
    querySelectorAll(){ return []; },
    scrollIntoView(){},
  };
  return node;
};
const nodes = new Map();
const get = (id) => {
  if (!ids.has(id)) return null;
  if (!nodes.has(id)) nodes.set(id, el(id));
  return nodes.get(id);
};

// Stub responses shaped like the real endpoints.
const RESPONSES = {
  "/api/entities": { person: { entity: "person", fields: [], field_names: ["name"] },
                     place: { entity: "place", fields: [], field_names: ["name"] } },
  "/api/packs": [{ id: "p/pack.csv", name: "p", rows: 2, format: "csv" }],
  "/api/pack": { rows: [{ decision_id: "d1", decision: "review", score: "0.7",
                          evidence: "{}", reg_name: "x", sur_name: "y" }],
                 fields: ["decision_id", "decision", "score", "evidence",
                          "reg_name", "sur_name"],
                 digest: "abc", content_digest: "abc", manifest: {},
                 sides: ["reg", "sur"], format: "csv", problems: [],
                 outcome_decision: { same_entity: "match", different: "no_match",
                                     unresolved: "review" },
                 outcomes: ["same_entity", "different", "unresolved"] },
  "/api/marks": { current: {}, outstanding: 1, summary: { marked: 0, by_outcome: {} } },
  "/api/documents": { jurisdiction: "NG", revealed: false, counts: { PERSON: 2 },
    documents: [{ name: "a.txt", chars: 10, text: "[PERSON]", entities: [
      { id: "e1", type: "PERSON", span: [0, 8], confidence: 0.9, detector: "gliner",
        shown: "[PERSON]", placeholder: "[PERSON]", masked: true,
        action: "uncovered", authority: "", rationale: "no rule" }] }],
    links: [{ type: "PERSON", a_doc: "a.txt", b_doc: "b.txt", a_id: "e1", b_id: "e2",
      a: "[PERSON]", b: "[PERSON]", decision: "review", score: 0.68,
      distinctive_max: 0.5, evidence: {}, decision_id: "xwd:sha256:x" }] },
  "/api/compare": { decision: "review", score: 1.0, evidence: {},
    distinctive_max: 0.56, distinctive_floor: 0.75, pins: {} },
};

const sandbox = {
  console,
  document: {
    querySelector: (sel) => (sel.startsWith("#") ? get(sel.slice(1)) : el("q")),
    querySelectorAll: () => [],
    createElement: () => el("new"),
    addEventListener(){},
    body: el("body"),
  },
  window: { addEventListener(){} },
  FileReader: class { readAsDataURL(){} },
  fetch: async (url) => {
    const path = String(url).split("?")[0];
    if (!(path in RESPONSES)) errors.push(`fetch to unstubbed ${path}`);
    return { json: async () => RESPONSES[path] ?? {} };
  },
  setTimeout, clearTimeout,
};
sandbox.globalThis = sandbox;

try {
  vm.createContext(sandbox);
  new vm.Script(script).runInContext(sandbox);
} catch (e) {
  errors.push(`threw while loading: ${e.message}`);
}

// Let the boot IIFE settle.
await new Promise((r) => setTimeout(r, 300));

// Then exercise every control the page binds, the way a click would.
const fns = [...script.matchAll(/function\s+([A-Za-z_$][\w$]*)/g)].map(m => m[1]);
for (const name of ["tab", "draw", "drawDocs", "queued", "markUnused",
                    "describeEntity", "example", "dexample", "loadPacks"]) {
  if (!fns.includes(name) && typeof sandbox[name] !== "function") continue;
  try {
    if (name === "tab") ["compare","extract","places","redact","verify","review"]
      .forEach(t => sandbox.tab(t));
    else sandbox[name]();
  } catch (e) {
    errors.push(`${name}() threw: ${e.message}`);
  }
}

if (errors.length) { errors.forEach(e => console.log("  FAIL " + e)); process.exit(1); }
console.log("  boot and every tab switch ran clean");
