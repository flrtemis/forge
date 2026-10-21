/* FORGE — setup / self-test page. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var TOKEN = new URLSearchParams(location.search).get("token") || "";
  var base = location.href.replace(/\/[^\/]*$/, "");

  function api(path) {
    return base + path + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "");
  }

  function say(msg, bad) {
    $("test-status").textContent = msg;
    $("test-status").className = "status" + (bad ? " error" : "");
  }

  /* ---- 1: end-to-end test ---- */
  function test() {
    say("synthesising…");
    var t0 = performance.now();
    fetch(api("/speak"), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" },
        TOKEN ? { "X-Forge-Token": TOKEN } : {}),
      body: JSON.stringify({
        text: "This is my voice, running on my own machine. It was trained from my recordings."
      })
    }).then(function (r) {
      if (!r.ok) return r.text().then(function (t) {
        var m = t; try { m = JSON.parse(t).error || t; } catch (e) {}
        throw new Error(m);
      });
      return r.blob();
    }).then(function (blob) {
      var ms = Math.round(performance.now() - t0);
      var audio = new Audio(URL.createObjectURL(blob));
      audio.play();
      say("✓ " + ms + " ms · " + Math.round(blob.size / 1024) + " KB");
      $("detail").textContent =
        "First call includes loading the model into VRAM.\n" +
        "Subsequent sentences are much faster — that is the number that matters.";
    }).catch(function (e) {
      say("✗ " + String(e.message || e).split("\n")[0], true);
      $("detail").textContent = String(e.message || e);
    });
  }

  /* ---- health ---- */
  function health() {
    fetch(api("/health")).then(function (r) { return r.json(); }).then(function (j) {
      var name = $("voice-name");
      if (!j.voice) {
        name.textContent = "no voice set — restart with --voice";
        name.className = "pill warn";
        return;
      }
      name.textContent = (j.name || "voice") + (j.loaded ? " · loaded" : " · ready");
      name.className = "pill ok";
    }).catch(function () {
      $("voice-name").textContent = "server unreachable";
      $("voice-name").className = "pill warn";
    });
  }

  /* ---- 3: bookmarklet ---- */
  function bookmarkletSource(server, token) {
    var js = [
      "(function(){",
      "var s=(window.getSelection()||'').toString().trim();",
      "if(!s){alert('FORGE: select some text first, then click Read Aloud.');return;}",
      "var B=" + JSON.stringify(server) + ",T=" + JSON.stringify(token) + ";",
      "var q=s.split(/\\n+/).map(function(x){return x.replace(/\\s+/g,' ').trim();})",
      "  .filter(function(x){return x.length>1;});",
      "var a=new Audio();",
      "function next(i){",
      "  if(i>=q.length){return;}",
      "  fetch(B+'/speak'+(T?'?token='+encodeURIComponent(T):''),{",
      "    method:'POST',",
      "    headers:Object.assign({'Content-Type':'application/json'},T?{'X-Forge-Token':T}:{}),",
      "    body:JSON.stringify({text:q[i]})",
      "  }).then(function(r){",
      "    if(!r.ok){return r.text().then(function(t){throw new Error(t);});}",
      "    return r.blob();",
      "  }).then(function(b){",
      "    a.src=URL.createObjectURL(b);",
      "    a.onended=function(){URL.revokeObjectURL(a.src);next(i+1);};",
      "    a.play();",
      "  }).catch(function(e){",
      "    alert('FORGE server not reachable at '+B+'\\nStart it: python -m forge.server\\n\\n'+e.message);",
      "  });",
      "}",
      "next(0);",
      "})();"
    ].join("");
    return "javascript:" + js;
  }

  function rebuild() {
    var server = ($("server").value || base).replace(/\/+$/, "");
    var token = $("token").value.trim();
    $("bookmarklet").setAttribute("href", bookmarkletSource(server, token));
    $("bm-note").textContent =
      "Drag the button to your bookmarks toolbar. If a page refuses it " +
      "(some sites block javascript: links via CSP, and https pages may block " +
      "the localhost request), use the add-on instead.";
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("test").addEventListener("click", test);
    $("rebuild").addEventListener("click", rebuild);
    $("server").value = base;
    $("bookmarklet").setAttribute("draggable", "true");
    rebuild();
    health();
  });
})();
