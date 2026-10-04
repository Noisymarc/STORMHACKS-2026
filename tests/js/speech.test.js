// Plain Node tests (no dependencies) for frontend/speech.js. Run: node tests/js/speech.test.js
const assert = require('assert');
const path = require('path');
const { splitSpeech, isEcho, rememberSpoken, SpeechQueue } = require(path.join(__dirname, '../../frontend/speech.js'));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const tick = () => new Promise((r) => setImmediate(r));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

// ---- splitSpeech ----------------------------------------------------------------------
test('Japanese: splits at 。 with no space after it', () => {
  const r = splitSpeech('これはテストです。次の文です。まだ途中');
  assert.deepStrictEqual(r.chunks, ['これはテストです。', '次の文です。']);
  assert.strictEqual(r.rest, 'まだ途中');
});

test('Japanese: ！？ and fullwidth punctuation end a sentence immediately', () => {
  assert.deepStrictEqual(splitSpeech('本当ですか？はい！').chunks, ['本当ですか？', 'はい！']);
});

test('closing quotes stay with their sentence', () => {
  assert.deepStrictEqual(splitSpeech('彼は「行く。」と言った。').chunks, ['彼は「行く。」', 'と言った。']);
});

test('Latin: needs a space after the full stop', () => {
  const r = splitSpeech('Hello. How are you? Fine');
  assert.deepStrictEqual(r.chunks, ['Hello.', 'How are you?']);
  assert.strictEqual(r.rest.trim(), 'Fine');
});

test('a decimal point is not a sentence end', () => {
  const r = splitSpeech('It costs 3.5 euros');
  assert.deepStrictEqual(r.chunks, []);
  assert.strictEqual(r.rest, 'It costs 3.5 euros');
});

test('unfinished sentence waits, then force flushes it', () => {
  assert.deepStrictEqual(splitSpeech('Fin.').chunks, []);              // might be "Fin.5"
  assert.deepStrictEqual(splitSpeech('Fin.', { force: true }), { chunks: ['Fin.'], rest: '' });
});

test('long Japanese clause is spoken early at 、', () => {
  const clause = 'あ'.repeat(35) + '、';
  const r = splitSpeech(clause + 'つづき');
  assert.deepStrictEqual(r.chunks, [clause]);
  assert.strictEqual(r.rest, 'つづき');
});

test('short clause is not cut at 、', () => {
  assert.deepStrictEqual(splitSpeech('はい、そうです').chunks, []);
});

test('text with no punctuation is capped well below the 1000-character request limit', () => {
  const long = 'あ'.repeat(5000);
  const forced = splitSpeech(long, { force: true });
  assert.ok(forced.chunks.length >= 25);
  assert.ok(forced.chunks.every((c) => c.length <= 200), 'every chunk <= 200 chars');
  assert.strictEqual(forced.chunks.join(''), long);
  assert.strictEqual(forced.rest, '');
  assert.ok(splitSpeech(long).rest.length < 200);                      // growth is bounded while streaming
});

test('Latin text is cut at a space, not mid-word, when too long', () => {
  const words = Array(80).fill('word').join(' ');
  const r = splitSpeech(words, { force: true });
  assert.ok(r.chunks.every((c) => c.length <= 200 && !c.startsWith('ord') && c.endsWith('word')));
});

test('punctuation-only pieces are dropped', () => {
  assert.deepStrictEqual(splitSpeech('。。。', { force: true }).chunks, []);
  assert.deepStrictEqual(splitSpeech('  ', { force: true }).chunks, []);
});

test('streaming one character at a time gives the same sentences', () => {
  const text = 'これはテストです。次の文です。最後';
  let buffer = '', spoken = [];
  for (const ch of text) {
    buffer += ch;
    const { chunks, rest } = splitSpeech(buffer);
    spoken.push(...chunks); buffer = rest;
  }
  spoken.push(...splitSpeech(buffer, { force: true }).chunks);
  assert.deepStrictEqual(spoken, ['これはテストです。', '次の文です。', '最後']);
});

// ---- echo guard -----------------------------------------------------------------------
test('isEcho recognises our own recent speech, ignoring punctuation and case', () => {
  const recent = []; rememberSpoken(recent, 'こんにちは、今日は良い天気ですね。', 1000);
  assert.ok(isEcho('今日は良い天気ですね', recent, 2000));
  assert.ok(!isEcho('明日は雨が降るでしょう', recent, 2000));
  assert.ok(!isEcho('はい', recent, 2000), 'short fragments are never echoes');
  assert.ok(!isEcho('今日は良い天気ですね', recent, 1000 + 60000), 'old speech expires');
});

test('isEcho also catches near-matches and text spanning two spoken phrases', () => {
  const recent = [];
  rememberSpoken(recent, 'これは最初の文です。', 1000);
  rememberSpoken(recent, 'そして次の文が続きます。', 2000);
  assert.ok(isEcho('これは最初の文です。そして次の文', recent, 3000), 'spans two phrases');
  assert.ok(isEcho('これは最初の分です', recent, 3000), 'one character mis-recognised');
  assert.ok(!isEcho('量子力学の基礎について説明します', recent, 3000), 'new content is not an echo');
  assert.ok(!isEcho('これは全く別の話題です', recent, 3000), 'sharing a few words is not enough');
});

test('rememberSpoken keeps only the latest entries', () => {
  const recent = [];
  for (let i = 0; i < 20; i++) rememberSpoken(recent, 'phrase ' + i, i);
  assert.strictEqual(recent.length, 8);
});

// ---- SpeechQueue ----------------------------------------------------------------------
function harness(opts = {}) {
  const log = { synth: [], played: [], released: [], errors: [], aborted: [] };
  const synths = [];                                  // controllable synthesize() calls
  const plays = [];                                   // controllable play() calls
  const q = new SpeechQueue({
    synthesize: (text, signal) => {
      const d = deferred(); synths.push({ text, d, signal }); log.synth.push(text);
      signal.addEventListener('abort', () => { log.aborted.push(text); const e = new Error('aborted'); e.name = 'AbortError'; d.reject(e); });
      return d.promise;
    },
    play: (url, register) => { const d = deferred(); plays.push({ url, d }); log.played.push(url); register(() => d.resolve()); return d.promise; },
    release: (url) => log.released.push(url),
    onError: (e) => log.errors.push(e.message),
    ...opts,
  });
  return { q, log, synths, plays };
}
const settle = async () => { for (let i = 0; i < 4; i++) await tick(); };

test('phrases play in order, one at a time', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('a'); q.enqueue('b');
  synths[0].d.resolve('ua'); synths[1].d.resolve('ub'); await settle();
  assert.deepStrictEqual(log.played, ['ua']);         // b waits for a to finish
  plays[0].d.resolve(); await settle();
  assert.deepStrictEqual(log.played, ['ua', 'ub']);
  plays[1].d.resolve(); await settle();
  assert.deepStrictEqual(log.released, ['ua', 'ub']);
});

test('the next phrase is requested while the current one plays (no per-phrase latency)', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('a'); q.enqueue('b'); q.enqueue('c');
  assert.deepStrictEqual(log.synth, ['a', 'b']);      // a loading, b pre-requested, c waits
  synths[0].d.resolve('ua'); await settle();
  assert.strictEqual(plays.length, 1);                // a is playing...
  assert.deepStrictEqual(log.synth, ['a', 'b']);      // ...b already loading, c still waiting
  plays[0].d.resolve(); await settle();
  assert.deepStrictEqual(log.synth, ['a', 'b', 'c']); // c starts loading as b starts playing
});

test('queue is capped: when behind, the oldest waiting phrase is dropped', async () => {
  const { q, log, synths, plays } = harness({ maxQueue: 3 });
  for (const t of ['p0', 'p1', 'p2', 'p3', 'p4', 'p5']) q.enqueue(t);
  assert.ok(log.aborted.includes('p1'), 'a phrase that was already loading is aborted when dropped');
  synths[0].d.resolve('u0'); await settle(); plays[0].d.resolve(); await settle();
  const spoken = log.synth.filter((t) => !log.aborted.includes(t));
  assert.deepStrictEqual(spoken, ['p0', 'p3', 'p4']); // p1, p2 were dropped; p4 is pre-requested while p3 plays
  assert.ok(q.pending <= 4);
});

test('Stop while a request is still loading: audio never plays', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('hello'); q.enqueue('more');
  q.stop();
  assert.deepStrictEqual(log.aborted.sort(), ['hello', 'more'], 'in-flight requests were aborted');
  await settle();
  assert.strictEqual(plays.length, 0, 'nothing was played');
  assert.strictEqual(q.pending, 0);
});

test('Stop when the response had already arrived (abort lost the race): not played, url released once', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('hello');
  synths[0].d.resolve('late-url');                    // response arrives in the same moment...
  q.stop();                                           // ...as Stop is pressed
  await settle();
  assert.strictEqual(plays.length, 0);
  assert.deepStrictEqual(log.released, ['late-url']);
});

test('Stop while a fetch fails with AbortError: no error is reported', async () => {
  const { q, log } = harness();
  q.enqueue('hello'); q.stop(); await settle();
  assert.deepStrictEqual(log.errors, []);
});

test('Stop during playback cuts the audio, clears the queue and cancels the pre-requested phrase', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('a'); q.enqueue('b');
  synths[0].d.resolve('ua'); await settle();
  assert.strictEqual(plays.length, 1);
  q.stop(); await settle();
  assert.deepStrictEqual(log.aborted, ['b']);        // the pre-requested phrase is cancelled
  assert.deepStrictEqual(log.released, ['ua']);       // current audio freed exactly once
  assert.strictEqual(q.pending, 0);
  assert.strictEqual(plays.length, 1, 'b never played');
});

test('speech works normally again after Stop', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('old'); q.stop(); await settle();
  q.enqueue('new');
  assert.deepStrictEqual(log.synth, ['old', 'new']);
  synths[1].d.resolve('u-new'); await settle();
  assert.deepStrictEqual(log.played, ['u-new']);
  plays[0].d.resolve(); await settle();
});

test('a failed request is reported once and the queue carries on', async () => {
  const { q, log, synths, plays } = harness();
  q.enqueue('a'); q.enqueue('b');
  synths[0].d.reject(new Error('ElevenLabs is rate limiting')); await settle();
  assert.deepStrictEqual(log.errors, ['ElevenLabs is rate limiting']);
  synths[1].d.resolve('ub'); await settle();
  assert.deepStrictEqual(log.played, ['ub']);
});

test('onPlaying reports start and end of audio, and not for phrases that never played', async () => {
  const states = [];
  const { q, synths, plays } = harness({ onPlaying: (v) => states.push(v) });
  q.enqueue('a'); synths[0].d.resolve('u'); await settle(); plays[0].d.resolve(); await settle();
  assert.deepStrictEqual(states, [true, false]);
  q.enqueue('b'); q.stop(); await settle();
  assert.deepStrictEqual(states, [true, false]);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log('ok   ' + name); }
    catch (error) { failed++; console.log('FAIL ' + name + '\n     ' + (error && error.message)); }
  }
  console.log(`\n${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
