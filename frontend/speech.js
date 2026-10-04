/* Spoken-translation helpers for live.html. Plain script (no build step); also loadable from
 * Node (module.exports) so tests/test_speech_js.py can exercise it without a browser.
 *
 *  - splitSpeech:  cut the streaming translation into speakable chunks. Works for text with no
 *                  spaces after punctuation (Japanese) and caps chunk length.
 *  - isEcho:       recognise text that is just our own spoken translation coming back through the
 *                  microphone, so it is not spoken again (replaces muting the mic).
 *  - SpeechQueue:  bounded playback queue whose stop() also cancels a request that is still loading.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Speech = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const HARD = '。！？!?…‥．';                 // always end a sentence
  const SOFT = '、，';                          // clause break: speak early once long enough
  const CLOSERS = '」』）】〕》〉”’)"\']';       // closing quotes/brackets stay with the sentence
  const CJK = /[぀-ヿ㐀-鿿ｦ-ﾟ]/;
  const SPEAKABLE = /[\p{L}\p{N}]/u;
  const DEFAULTS = { maxChars: 200, softMin: 30 };

  function isSpace(ch) { return ch !== undefined && /\s/.test(ch); }

  // Index just past the first chunk to speak, or 0 if the text should keep growing.
  function findCut(text, { maxChars, softMin }) {
    let lastBreak = 0;                           // last soft/space position inside the window
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      const next = text[i + 1];
      let cut = 0;
      if (HARD.includes(ch)) {
        cut = i + 1;
      } else if (ch === '.') {
        // A Latin full stop ends a sentence only when followed by a space (so 3.5 is safe), or
        // when it follows Japanese text and is not part of a number or word.
        if (isSpace(next)) cut = i + 1;
        else if (next !== undefined && i > 0 && CJK.test(text[i - 1]) && !/[A-Za-z0-9]/.test(next)) cut = i + 1;
      } else if (SOFT.includes(ch) || (ch === ',' && isSpace(next))) {
        if (i + 1 >= (ch === ',' ? softMin + 10 : softMin)) cut = i + 1;
        else lastBreak = i + 1;
      } else if (isSpace(ch)) {
        lastBreak = i + 1;
      }
      if (cut) {
        while (cut < text.length && (HARD.includes(text[cut]) || CLOSERS.includes(text[cut]))) cut++;
        return cut;
      }
      if (i + 1 >= maxChars) return lastBreak > maxChars / 2 ? lastBreak : i + 1;
    }
    return 0;
  }

  /* Returns { chunks, rest }. `rest` is text still waiting for its sentence to finish.
   * With force=true (idle / stop) everything is returned as chunks and rest is ''. */
  function splitSpeech(buffer, opts = {}) {
    const o = { ...DEFAULTS, ...opts };
    const chunks = [];
    let rest = buffer;
    const push = (piece) => { piece = piece.trim(); if (SPEAKABLE.test(piece)) chunks.push(piece); };
    for (let cut = findCut(rest, o); cut > 0; cut = findCut(rest, o)) {
      push(rest.slice(0, cut));
      rest = rest.slice(cut);
    }
    if (o.force) {          // the loop above already capped every piece at maxChars
      push(rest);
      rest = '';
    }
    return { chunks, rest };
  }

  // ---- echo guard ------------------------------------------------------------------------
  const normalize = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

  const bigrams = (n) => { const set = new Set(); for (let i = 0; i + 1 < n.length; i++) set.add(n.slice(i, i + 2)); return set; };

  /* True if `text` is (a piece of) something we spoke recently. `recent` is a list of
   * { norm, at } entries (see rememberSpoken). Matches exact pieces, text that spans two spoken
   * phrases, and near-matches (speech recognition rarely returns our own voice letter for
   * letter): >= 70% of its character pairs must appear in what we said. Short fragments are
   * never treated as echoes. */
  function isEcho(text, recent, now = Date.now(), windowMs = 25000, minChars = 6) {
    const n = normalize(text);
    if (n.length < minChars) return false;
    const joined = recent.filter((r) => now - r.at <= windowMs).map((r) => r.norm).join('');
    if (!joined) return false;
    if (joined.includes(n)) return true;
    const mine = bigrams(n), theirs = bigrams(joined);
    let shared = 0;
    for (const pair of mine) if (theirs.has(pair)) shared++;
    return mine.size > 0 && shared / mine.size >= 0.7;
  }

  function rememberSpoken(recent, text, now = Date.now(), keep = 8) {
    recent.push({ norm: normalize(text), at: now });
    while (recent.length > keep) recent.shift();
  }

  // ---- playback queue --------------------------------------------------------------------
  /* synthesize(text, signal) -> Promise<url>   fetch the audio; must honour the AbortSignal
   * play(url, register)      -> Promise        resolve when finished; call register(stopFn)
   *                                            so stop() can cut it off
   * release(url)             -> void           free the url (URL.revokeObjectURL)
   *
   * Phrases play one at a time, but the next one is requested while the current one plays, so
   * a continuous lecture does not pay the request latency again for every phrase. At most
   * maxQueue phrases wait; when speech falls behind, the oldest waiting phrase is dropped. */
  class SpeechQueue {
    constructor({ synthesize, play, release = () => {}, maxQueue = 3, prefetch = 1,
                  onError = () => {}, onPlaying = () => {} }) {
      Object.assign(this, { synthesize, play, release, maxQueue, prefetch, onError, onPlaying });
      this.items = [];         // waiting phrases: { text, controller, promise }
      this.current = null;     // phrase being loaded or played
      this.epoch = 0;          // bumped by stop(): anything started before it is discarded
      this.playing = false;
      this.stopPlayback = null;
    }

    get pending() { return this.items.length + (this.playing ? 1 : 0); }

    enqueue(text) {
      this.items.push({ text, controller: null, promise: null });
      while (this.items.length > this.maxQueue) this._discard(this.items.shift());
      this._play();
      this._prefetch();
    }

    stop() {
      this.epoch++;
      for (const item of this.items) this._discard(item);
      this.items.length = 0;
      // The phrase in hand: abort its request if still loading (play() frees its url itself).
      if (this.current && !this.current.loaded) this._discard(this.current, false);
      if (this.stopPlayback) this.stopPlayback();          // audio already playing
    }

    _start(item) {
      item.controller = new AbortController();
      try { item.promise = Promise.resolve(this.synthesize(item.text, item.controller.signal)); }
      catch (error) { item.promise = Promise.reject(error); }   // a synchronous failure is reported like any other
      item.promise.catch(() => {});                        // reported when its turn comes
    }

    _prefetch() {
      for (const item of this.items.slice(0, this.prefetch)) if (!item.promise) this._start(item);
    }

    _discard(item, release = true) {
      if (item.controller) item.controller.abort();
      if (release && item.promise) item.promise.then((url) => this.release(url), () => {});
      item.discarded = true;
    }

    async _play() {
      if (this.playing || !this.items.length) return;
      this.playing = true;
      const epoch = this.epoch;
      const item = this.current = this.items.shift();
      if (!item.promise) this._start(item);
      this._prefetch();                                    // the next phrase starts loading now
      let url = null, started = false;
      try {
        url = await item.promise;
        item.loaded = true;
        if (epoch !== this.epoch || item.discarded) return;   // Stop was pressed while loading
        started = true;
        this.onPlaying(true);
        await this.play(url, (stopFn) => { this.stopPlayback = stopFn; });
      } catch (error) {
        if (epoch === this.epoch && !(error && error.name === 'AbortError')) this.onError(error);
      } finally {
        if (url) this.release(url);
        if (started) this.onPlaying(false);
        this.current = null;
        this.stopPlayback = null;
        this.playing = false;
        this._play();
        this._prefetch();
      }
    }
  }

  return { splitSpeech, isEcho, rememberSpoken, normalize, SpeechQueue };
});
