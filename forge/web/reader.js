/* FORGE reader — your voice, in your browser. No frameworks, no CDN. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var TOKEN = new URLSearchParams(location.search).get("token") || "";

  var base = location.href.replace(/[^\/]*$/, "").replace(/\/$/, "");

  function api(path) {
    return base + path + (TOKEN ? (path.indexOf("?") > -1 ? "&" : "?") + "token=" + encodeURIComponent(TOKEN) : "");
  }

  // ---- state ---------------------------------------------------------
  var queue = [];          // [{text, audio:null, status:'pending'|'loading'|'ready'|'error'}]
  var cursor = 0;          // which sentence is playing
  var playing = false;
  var gen = 0;             // bumped on stop/restart so stale fetches are dropped
  var wav = new Audio();
  wav.preload = "auto";

  // ---- sentence splitting -------------------------------------------
  // Words that end in a period but do not end a sentence.
  var ABBREV = new RegExp("^(mr|mrs|ms|dr|prof|rev|hon|st|sr|jr|vs|etc|no|fig|" +
    "approx|inc|ltd|co|dept|univ|ave|blvd|rd|jan|feb|mar|apr|jun|jul|aug|sept?|" +
    "oct|nov|dec|a\\.m|p\\.m|u\\.s|e\\.g|i\\.e)$", "i");

  function mergeAbbreviations(parts) {
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      var bare = p.replace(/[.!?…"'”’)\]]+$/, "").trim();
      if (ABBREV.test(bare) && i + 1 < parts.length) {
        parts[i + 1] = p + " " + parts[i + 1];
      } else {
        out.push(p);
      }
    }
    return out;
  }

  function splitSentences(text) {
    text = text.replace(/\r/g, "");
    var blocks = text.split(/\n{2,}/);          // paragraphs
    var out = [];
    blocks.forEach(function (block) {
      // Split on sentence enders, but not inside "Dr." / "1.5" / "e.g."
      var parts = block
        .replace(/\s+/g, " ")
        .split(/(?<=[.!?…])["'”’)]*\s+(?=[A-Z0-9"'“¿¡(])/);
      parts = mergeAbbreviations(parts.map(function (p) { return p.trim(); })
        .filter(Boolean));
      parts.forEach(function (p) {
        if (!p) return;
        // A 40-word "sentence" is usually a run-on; cut it at commas too.
        if (p.split(/\s+/).length > 45) {
          p.split(/(?<=[,;:])\s+(?=and |but |which |who |because |so )/).forEach(function (q) {
            q = q.trim();
            if (q) out.push(q);
          });
        } else {
          out.push(p);
        }
      });
    });
    return out;
  }

  // ---- speech fetch --------------------------------------------------
  function fetchAudio(item, myGen) {
    item.status = "loading";
    item.controller = new AbortController();
    return fetch(api("/speak"), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" },
        TOKEN ? { "X-Forge-Token": TOKEN } : {}),
      body: JSON.stringify({
        text: item.text,
        lang: $("lang").value,
        speed: parseFloat($("speed").value) || 1.0,
        temperature: parseFloat($("temp").value)
      }),
      signal: item.controller.signal
    }).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          var msg = t;
          try { msg = JSON.parse(t).error || t; } catch (e) {}
          throw new Error(msg);
        });
      }
      return r.blob();
    }).then(function (blob) {
      if (myGen !== gen) return null;
      item.audio = URL.createObjectURL(blob);
      item.status = "ready";
      return item.audio;
    }).catch(function (e) {
      if (e.name === "AbortError" || myGen !== gen) return null;
      item.status = "error";
      status("Could not synthesise: " + e.message, true);
      throw e;
    });
  }

  function ensureAudio(i) {
    var myGen = gen;
    var item = queue[i];
    if (!item) return Promise.resolve(null);
    if (item.audio) return Promise.resolve(item.audio);
    if (item.pending) return item.pending;
    item.pending = fetchAudio(item, myGen).then(function (url) {
      item.pending = null;
      return url;
    }, function (e) {
      item.pending = null;
      throw e;
    });
    return item.pending;
  }

  // ---- playback ------------------------------------------------------
  function status(msg, isError) {
    $("status").textContent = msg || "";
    $("status").className = isError ? "status error" : "status";
  }

  function playFrom(i) {
    cursor = i;
    if (i >= queue.length) {
      playing = false;
      wav.onended = null;
      cursor = 0;                       // Play starts over from the top
      markAll("done");
      status("Done — " + queue.length + " sentences.");
      setButtons();
      return;
    }
    markAll(null);
    queue[i].status = "speaking";
    markLine(i);
    status("Speaking " + (i + 1) + " / " + queue.length + " …");
    setButtons();
    ensureAudio(i).then(function (url) {
      if (!url) return;
      prefetch(i + 1);
      wav.src = url;
      wav.playbackRate = 1.0;
      wav.onended = function () {
        if (!playing) return;
        playFrom(i + 1);
      };
      wav.play().catch(function (e) {
        status("Firefox blocked autoplay: press Play again. (" + e.message + ")", true);
        playing = false;
        setButtons();
      });
    }).catch(function () { playing = false; setButtons(); });
  }

  function prefetch(i) {
    if (i < queue.length) ensureAudio(i).catch(function () {});
  }

  function setButtons() {
    $("play").disabled = playing || !queue.length;
    $("stop").disabled = !playing;
    $("play").textContent = cursor > 0 && !playing ? "Resume" : "Play";
  }

  function markAll(state) {
    var lines = $("lines").children;
    for (var i = 0; i < lines.length; i++) {
      lines[i].className = "line" + (state ? " " + state : "");
    }
  }

  function markLine(i) {
    var el = $("lines").children[i];
    if (!el) return;
    el.className = "line speaking";
    if (el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  // Pause and drop in-flight audio, but keep the queue so Play resumes.
  function halt() {
    gen++;
    playing = false;
    wav.onended = null;
    wav.pause();
    wav.removeAttribute("src");
  }

  // Full reset: everything cached for this text goes away.
  function reset() {
    halt();
    q_clear();
    markAll(null);
    setButtons();
  }

  function q_clear() {
    queue.forEach(function (it) {
      if (it.controller) it.controller.abort();
      if (it.audio) URL.revokeObjectURL(it.audio);
      it.audio = null;
      it.pending = null;
    });
    queue = [];
  }

  // ---- page wiring ---------------------------------------------------
  function renderLines() {
    var box = $("lines");
    box.innerHTML = "";
    queue.forEach(function (item, i) {
      var div = document.createElement("div");
      div.className = "line";
      div.textContent = item.text;
      div.title = "Click to read from here";
      div.addEventListener("click", function () {
        halt();
        playing = true;
        playFrom(i);
      });
      box.appendChild(div);
    });
  }

  function readAloud() {
    var text = $("text").value.trim();
    if (!text) { status("Paste some text first.", true); return; }
    reset();
    var sentences = splitSentences(text);
    if (!sentences.length) { status("Nothing speakable in that text.", true); return; }
    queue = sentences.map(function (s) {
      return { text: s, audio: null, status: "pending", pending: null, controller: null };
    });
    $("reader").hidden = false;
    $("paste").hidden = true;
    renderLines();
    playing = true;
    status("Loading your voice on the first sentence — this can take ~20 s once.");
    playFrom(0);
  }

  var checkTimer = null;

  function checkServer(retry) {
    if (checkTimer) { clearTimeout(checkTimer); checkTimer = null; }
    fetch(api("/health"))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.voice) {
          $("voice-name").textContent = "no voice loaded";
          $("voice-name").className = "pill warn";
          status("Server is up but no voice is set. Start it with --voice <folder>.", true);
          return;
        }
        $("voice-name").textContent = j.loaded ? (j.name || "voice") : "ready (model loads on first line)";
        $("voice-name").className = "pill " + (j.loaded ? "ok" : "");
        if (j.languages && j.languages.length) {
          var sel = $("lang");
          sel.innerHTML = "";
          j.languages.forEach(function (l) {
            var o = document.createElement("option");
            o.value = l; o.textContent = l;
            sel.appendChild(o);
          });
          sel.value = j.languages.indexOf("en") > -1 ? "en" : j.languages[0];
        }
      })
      .catch(function () {
        $("voice-name").textContent = "server offline";
        $("voice-name").className = "pill warn";
        status("Can't reach the FORGE server (yet). Start it with `python -m forge.server` — this page retries by itself.", true);
        checkTimer = setTimeout(function () { checkServer(true); }, 3000);
      });
  }

  // ---- init ----------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    $("go").addEventListener("click", readAloud);
    $("play").addEventListener("click", function () {
      if (!queue.length) return readAloud();
      playing = true;
      playFrom(cursor);
    });
    $("stop").addEventListener("click", function () {
      halt();
      markAll(null);
      setButtons();
      status("Stopped — Play resumes from line " + (cursor + 1) + ".");
    });
    $("back").addEventListener("click", function () {
      $("paste").hidden = false;
      $("reader").hidden = true;
      reset();
    });
    $("text").addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") readAloud();
    });
    $("temp").addEventListener("input", function () {
      $("temp-out").textContent = parseFloat($("temp").value).toFixed(2);
    });
    $("speed").addEventListener("input", function () {
      $("speed-out").textContent = parseFloat($("speed").value).toFixed(2) + "×";
    });
    setButtons();
    checkServer();
  });
})();
