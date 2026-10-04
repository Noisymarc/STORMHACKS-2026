/* Ordering for the "My glossary" list in live.html. Plain script (no build step); also loadable from
 * Node (module.exports) so tests/test_glossary_order_js.py can exercise it without a browser.
 *
 * The list always shows every saved phrase. Phrases that appear in the live transcript are moved to
 * the top, the one heard most recently first; everything else keeps its saved order below them.
 * "Appears" means exactly what the transcript highlight means (the same spans), so the two agree.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GlossaryOrder = api;
})(typeof self !== 'undefined' ? self : this, function () {
  /* spans: [{ start, memory }] as built by glossarySpans(). Returns Map(memory.id -> position of its
   * last appearance in the transcript). A later position means it was heard more recently. */
  function lastSeenFromSpans(spans) {
    const lastSeen = new Map();
    for (const span of spans) {
      const previous = lastSeen.get(span.memory.id);
      if (previous === undefined || span.start > previous) lastSeen.set(span.memory.id, span.start);
    }
    return lastSeen;
  }

  /* memories: the saved phrases in their saved order. Returns { items, heardIds }: `items` is every
   * memory exactly once, heard ones first (most recently heard first), then the rest in saved order. */
  function orderGlossary(memories, lastSeen) {
    const heard = [];
    const rest = [];
    memories.forEach((memory, index) => {
      if (lastSeen.has(memory.id)) heard.push({ memory, index, at: lastSeen.get(memory.id) });
      else rest.push(memory);
    });
    heard.sort((a, b) => b.at - a.at || a.index - b.index);
    return {
      items: [...heard.map((entry) => entry.memory), ...rest],
      heardIds: new Set(heard.map((entry) => entry.memory.id)),
    };
  }

  // Changes only when the list would look different, so the page can skip needless re-renders.
  function orderSignature({ items, heardIds }) {
    return items.map((memory) => memory.id + (heardIds.has(memory.id) ? '*' : '')).join(',');
  }

  return { lastSeenFromSpans, orderGlossary, orderSignature };
});
