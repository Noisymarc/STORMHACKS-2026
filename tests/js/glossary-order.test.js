// Plain Node tests (no dependencies) for frontend/glossary-order.js. Run: node tests/js/glossary-order.test.js
const assert = require('assert');
const path = require('path');
const { lastSeenFromSpans, orderGlossary, orderSignature } = require(path.join(__dirname, '../../frontend/glossary-order.js'));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const memory = (id) => ({ id, phrase: 'phrase ' + id });
const SAVED = ['a', 'b', 'c', 'd', 'e'].map(memory);                 // saved order: a b c d e
const ids = (result) => result.items.map((m) => m.id);
const span = (id, start) => ({ memory: memory(id), start });

test('nothing heard: the list is unchanged', () => {
  const result = orderGlossary(SAVED, new Map());
  assert.deepStrictEqual(ids(result), ['a', 'b', 'c', 'd', 'e']);
  assert.strictEqual(result.heardIds.size, 0);
});

test('a term that appears is brought to the top; the rest keep their order below', () => {
  const result = orderGlossary(SAVED, lastSeenFromSpans([span('d', 10)]));
  assert.deepStrictEqual(ids(result), ['d', 'a', 'b', 'c', 'e']);
  assert.deepStrictEqual([...result.heardIds], ['d']);
});

test('as more terms appear, the most recent is on top', () => {
  const spans = [span('d', 10)];
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeenFromSpans(spans))), ['d', 'a', 'b', 'c', 'e']);
  spans.push(span('b', 40));
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeenFromSpans(spans))), ['b', 'd', 'a', 'c', 'e']);
  spans.push(span('e', 80));
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeenFromSpans(spans))), ['e', 'b', 'd', 'a', 'c']);
});

test('a term heard again moves back to the top (the last appearance counts)', () => {
  const spans = [span('d', 10), span('b', 40), span('d', 90)];
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeenFromSpans(spans))), ['d', 'b', 'a', 'c', 'e']);
  assert.strictEqual(lastSeenFromSpans(spans).get('d'), 90);
});

test('span order does not matter, only positions in the transcript', () => {
  const forward = [span('a', 5), span('c', 50)];
  const backward = [...forward].reverse();
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeenFromSpans(forward))), ids(orderGlossary(SAVED, lastSeenFromSpans(backward))));
});

test('every saved phrase is always in the list, exactly once', () => {
  const lastSeen = lastSeenFromSpans([span('c', 3), span('a', 9), span('c', 30), span('e', 30.5)]);
  const result = orderGlossary(SAVED, lastSeen);
  assert.deepStrictEqual([...ids(result)].sort(), ['a', 'b', 'c', 'd', 'e']);
  assert.strictEqual(new Set(ids(result)).size, SAVED.length);
});

test('a phrase heard but no longer saved (removed or other language) does not appear', () => {
  const result = orderGlossary(SAVED, lastSeenFromSpans([span('zzz', 100), span('b', 5)]));
  assert.deepStrictEqual(ids(result), ['b', 'a', 'c', 'd', 'e']);
  assert.deepStrictEqual([...result.heardIds], ['b']);
});

test('ties fall back to the saved order', () => {
  const lastSeen = new Map([['c', 7], ['a', 7]]);
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeen)), ['a', 'c', 'b', 'd', 'e']);
});

test('an empty glossary and a new session (nothing heard) are fine', () => {
  assert.deepStrictEqual(ids(orderGlossary([], lastSeenFromSpans([span('a', 1)]))), []);
  assert.deepStrictEqual(ids(orderGlossary(SAVED, lastSeenFromSpans([]))), ['a', 'b', 'c', 'd', 'e']);
});

test('input is not modified', () => {
  const saved = SAVED.slice();
  orderGlossary(saved, lastSeenFromSpans([span('e', 1)]));
  assert.deepStrictEqual(saved.map((m) => m.id), ['a', 'b', 'c', 'd', 'e']);
});

test('signature changes only when the visible list changes', () => {
  const sig = (spans) => orderSignature(orderGlossary(SAVED, lastSeenFromSpans(spans)));
  assert.strictEqual(sig([span('d', 10)]), sig([span('d', 11)]));          // same term, later position: same list
  assert.notStrictEqual(sig([span('d', 10)]), sig([span('d', 10), span('b', 20)]));
  assert.notStrictEqual(sig([]), sig([span('a', 1)]));                     // 'a' is first either way, but now "heard"
  assert.strictEqual(sig([]), 'a,b,c,d,e');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); }
  catch (error) { failed++; console.log('FAIL ' + name + '\n     ' + (error && error.message)); }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
