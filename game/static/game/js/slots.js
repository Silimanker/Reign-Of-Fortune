/* Reign of Fortune – scatter-pay slot controller
 *
 * The server owns all outcomes. This file:
 *   1. Sends a spin request with the chosen stake.
 *   2. Animates the grid: each cell tumbles, winning cells glow, then collapse.
 *   3. Shows banners and updates the wallet display.
 *
 * No randomness happens here. The JS is purely cosmetic.
 */
(function () {
  "use strict";

  var cfgEl = document.getElementById("rof-config");
  if (!cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent);

  /* ── element refs ── */
  var spinBtn      = document.getElementById("spinBtn");
  var spinLabel    = document.getElementById("spinLabel");
  var stakeInput   = document.getElementById("stakeInput");
  var ringValue    = document.getElementById("ringValue");
  var balanceValue = document.getElementById("balanceValue");
  var winPotential = document.getElementById("winPotential");
  var winBanner    = document.getElementById("winBanner");
  var lossBanner   = document.getElementById("lossBanner");
  var winLabel     = document.getElementById("winLabel");
  var winAmount    = document.getElementById("winAmount");
  var cascadeLabel = document.getElementById("cascadeLabel");
  var winMsg       = document.getElementById("winMsg");
  var lossMsg      = document.getElementById("lossMsg");
  var winPopup     = document.getElementById("winPopup");
  var winPopupLabel = document.getElementById("winPopupLabel");
  var winPopupAmount = document.getElementById("winPopupAmount");
  var winPopupMeta = document.getElementById("winPopupMeta");
  var winPopupTimer = null;
  var favorBar     = document.getElementById("favorBar");
  var favorPct     = document.getElementById("favorPct");
  var bonusBar     = document.getElementById("bonusBar");
  var bonusSpinsLeft = document.getElementById("bonusSpinsLeft");
  var bonusMult    = document.getElementById("bonusMult");
  var featurePanel = document.getElementById("featurePanel");
  var featureOverlay = document.getElementById("featureOverlay");
  var featureOverlayText = document.getElementById("featureOverlayText");
  var closeFeatureOverlay = document.getElementById("closeFeatureOverlay");
  var featPlayed   = document.getElementById("featPlayed");
  var featBestMult = document.getElementById("featBestMult");
  var featTotal    = document.getElementById("featTotal");
  var gridEl       = document.getElementById("slotGrid");
  var csrfMeta     = document.querySelector('meta[name="csrf-token"]');
  var eventAlert = document.getElementById("eventAlert");
  var eventAlertIcons = document.getElementById("eventAlertIcons");
  var eventAlertTitle = document.getElementById("eventAlertTitle");
  var eventAlertMessages = document.getElementById("eventAlertMessages");
  var autoRollCount = document.getElementById("autoRollCount");
  var autoRollBtn = document.getElementById("autoRollBtn");
  var autoRollStatus = document.getElementById("autoRollStatus");

  /* ── symbol lookup (from server config) ── */
  var symMap = {};
  cfg.symbols.forEach(function (s) { symMap[s.key] = s; });

  /* ── state ── */
  var state = {
    spinning: false,
    balance:  cfg.player.balance,
    favor:    cfg.player.fortuneFavor,
    stake:    cfg.mode.default,
    rollTimer: null,
    autoActive: false,
    autoRemaining: 0,
    autoTimer: null,
    currentAutoSpin: false,
  };

  /* ──────────────── helpers ──────────────── */

  function money(v) {
    return Number(v).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function toast(msg, isError) {
    var host = document.getElementById("jsToasts");
    if (!host) {
      host = document.createElement("div");
      host.id = "jsToasts";
      host.className = "pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6";
      document.body.appendChild(host);
    }
    var el = document.createElement("div");
    el.className = "result-pop pointer-events-auto flex max-w-md items-start gap-3 rounded-xl border border-line bg-ink-3 px-4 py-3 shadow-2xl";
    var dot = isError ? "bg-ember" : "bg-jade";
    el.innerHTML = '<span class="mt-1 h-2 w-2 shrink-0 rounded-full ' + dot + '"></span><p class="text-sm leading-snug text-mist"></p>';
    el.querySelector("p").textContent = msg;
    host.appendChild(el);
    setTimeout(function () { el.remove(); }, 6000);
  }

  /* ──────────────── grid rendering ──────────────── */

  function makeCell(key) {
    var sym = symMap[key] || {};
    var el = document.createElement("div");
    el.className = "slot-cell slot-idle aspect-square flex items-center justify-center relative overflow-hidden";
    el.setAttribute("role", "gridcell");
    setCellSymbol(el, key);
    return el;
  }

  function setCellSymbol(el, key) {
    var sym = symMap[key] || {};
    el.dataset.key = key;
    el.setAttribute("aria-label", sym.name || key);
    var inner = document.createElement("div");
    inner.className = "flex flex-col items-center justify-center w-full h-full p-1";

    if (sym.icon) {
      var img = document.createElement("img");
      img.src   = sym.icon;
      img.alt   = sym.name || key;
      img.className = "w-full max-w-[80%] object-contain drop-shadow-sm";
      inner.appendChild(img);
    } else if (sym.glyph) {
      var span = document.createElement("span");
      span.textContent = sym.glyph;
      span.className   = "font-display text-lg font-bold";
      span.style.color = sym.color || "#e8eaef";
      inner.appendChild(span);
    }

    el.replaceChildren(inner);
  }

  function renderGrid(keys) {
    /* keys: array of 30 symbol-key strings */
    gridEl.innerHTML = "";
    keys.forEach(function (k) {
      gridEl.appendChild(makeCell(k));
    });
  }

  function highlightCells(indices, winColor) {
    var cells = gridEl.querySelectorAll(".slot-cell");
    indices.forEach(function (i) {
      var c = cells[i];
      if (!c) return;
      c.classList.remove("slot-idle");
      c.classList.add("slot-win");
      c.style.borderColor = winColor || "rgba(69,195,147,0.7)";
      c.style.background  = "rgba(69,195,147,0.12)";
      c.style.boxShadow   = "0 0 16px rgba(69,195,147,0.3)";
    });
  }

  function dimNonWinning(winIndices) {
    var cells = gridEl.querySelectorAll(".slot-cell");
    var set   = {};
    winIndices.forEach(function (i) { set[i] = true; });
    cells.forEach(function (c, i) {
      if (!set[i]) {
        c.style.opacity = "0.35";
      }
    });
  }

  function resetCells() {
    var cells = gridEl.querySelectorAll(".slot-cell");
    cells.forEach(function (c) {
      c.classList.remove("slot-win");
      c.style.borderColor = "";
      c.style.background  = "";
      c.style.boxShadow   = "";
      c.style.opacity     = "";
    });
  }

  function flashWinCells(cells) {
    /* brief pulse animation on winning cells */
    cells.forEach(function (i) {
      var c = gridEl.querySelectorAll(".slot-cell")[i];
      if (!c) return;
      c.style.transform = "scale(1.06)";
      setTimeout(function () { c.style.transform = ""; }, 250);
    });
  }

  /* ──────────────── scatter pip indicator ──────────────── */

  function updatePips(n) {
    var pips = document.querySelectorAll("[data-pip]");
    pips.forEach(function (p, idx) {
      var active = idx < n;
      p.style.borderColor = active ? "#9d7bf0" : "";
      p.style.background  = active ? "rgba(157,123,240,.35)" : "";
      p.style.boxShadow   = active ? "0 0 8px rgba(157,123,240,.6)" : "";
    });
  }

  /* ──────────────── wallet display ──────────────── */

  function paintWallet() {
    var txt = money(state.balance);
    if (ringValue)    ringValue.textContent    = txt;
    if (balanceValue) balanceValue.textContent = txt;

    var fv = Math.min(100, state.favor);
    if (favorBar) favorBar.style.width = fv + "%";
    if (favorPct) favorPct.textContent = fv + "%";
  }

  function paintPotential() {
    var stake = Number(stakeInput.value) || state.stake;
    /* Top paytable tier shown for one qualifying symbol cluster. */
    winPotential.textContent = money(stake * 500) + " SS";
  }

  /* ──────────────── spin ──────────────── */

  function setBusy(busy) {
    spinBtn.disabled = busy || state.autoActive;
    stakeInput.disabled = busy || state.autoActive;
    document.querySelectorAll("[data-stake]").forEach(function (b) {
      b.disabled = busy || state.autoActive;
    });
    syncAutoControls();
  }

  function syncAutoControls() {
    spinBtn.disabled = state.spinning || state.autoActive;
    stakeInput.disabled = state.spinning || state.autoActive;
    document.querySelectorAll("[data-stake]").forEach(function (b) {
      b.disabled = state.spinning || state.autoActive;
    });
    autoRollBtn.textContent = state.autoActive
      ? "Stop auto (" + state.autoRemaining + " left)"
      : "Start auto";
    autoRollBtn.setAttribute("aria-pressed", state.autoActive ? "true" : "false");
    autoRollBtn.disabled = state.spinning && !state.autoActive;
    autoRollCount.disabled = state.autoActive || state.spinning;
  }

  function stopAutoRoll(message) {
    var wasActive = state.autoActive;
    state.autoActive = false;
    state.autoRemaining = 0;
    window.clearTimeout(state.autoTimer);
    state.autoTimer = null;
    if (wasActive && message) autoRollStatus.textContent = message;
    syncAutoControls();
  }

  function startAutoRoll() {
    if (state.spinning) return;
    state.autoRemaining = Number(autoRollCount.value);
    if (!state.autoRemaining) return;
    state.autoActive = true;
    autoRollStatus.textContent = "Auto-roll active: " + state.autoRemaining + " spins remaining.";
    syncAutoControls();
    doSpin();
  }

  function showEventAlerts(data) {
    var messages = [];
    var icons = [];
    var notable = false;

    if (data.scatters > 0) {
      if (data.feature) {
        messages.push(data.scatters + " scatter seals — Heavenly Tribulation triggered.");
      } else {
        messages.push(data.scatters + " scatter seal" + (data.scatters === 1 ? "" : "s") +
          " landed; " + cfg.scatterMin + " needed to trigger the feature.");
      }
      icons.push("dao_emblem", "heavenly_tribulation");
    }

    (data.steps || []).forEach(function (step) {
      (step.wins || []).forEach(function (win) {
        var symbol = symMap[win.key];
        if (!symbol || symbol.tier !== "high") return;
        var message = symbol.name + " — " + win.count + " matching (" + win.tier +
          "), " + win.mult + "× stake";
        if (step.mult > 1) message += " × " + step.mult + " cascade multiplier";
        messages.push(message + ".");
        icons.push(symbol.key);
        notable = true;
      });
    });

    if (data.feature && data.feature.bestMult > 1) {
      messages.push("Free-spin cascade multiplier reached ×" +
        data.feature.bestMult.toFixed(1) + ".");
      icons.push("flying_sword");
      notable = true;
    }

    eventAlertIcons.replaceChildren();
    icons.slice(0, 3).forEach(function (key) {
      var symbol = symMap[key];
      if (!symbol || !symbol.icon) return;
      var icon = document.createElement("img");
      icon.src = symbol.icon;
      icon.alt = symbol.name;
      icon.className = "h-9 w-9 rounded-full border border-line bg-ink-3 object-contain p-1";
      eventAlertIcons.appendChild(icon);
    });
    eventAlertMessages.replaceChildren();
    messages.forEach(function (message) {
      var item = document.createElement("li");
      item.textContent = message;
      eventAlertMessages.appendChild(item);
    });
    eventAlertTitle.textContent = data.feature
      ? "Feature triggered"
      : notable ? "High-tier payout" : "Scatter alert";
    eventAlert.classList.toggle("hidden", messages.length === 0);
    return notable || Boolean(data.feature) || data.scatters > 0;
  }

  function startSpinAnimation() {
    var cells = gridEl.querySelectorAll(".slot-cell");
    cells.forEach(function (cell, index) {
      cell.classList.remove("slot-win");
      cell.classList.add("slot-spinning");
      cell.style.animationDelay = (index % 6) * 35 + "ms";
    });
    state.rollTimer = window.setInterval(function () {
      cells.forEach(function (cell) {
        var symbol = cfg.symbols[Math.floor(Math.random() * cfg.symbols.length)];
        setCellSymbol(cell, symbol.key);
      });
    }, 90);
  }

  function stopSpinAnimation() {
    window.clearInterval(state.rollTimer);
    state.rollTimer = null;
    var cells = gridEl.querySelectorAll(".slot-cell");
    cells.forEach(function (c) {
      c.classList.remove("slot-spinning");
      c.style.animationDelay = "";
    });
  }

  /* Animate a cascade chain: highlight cells, wait, then show next grid */
  function playCascades(steps, finalGrid, onDone) {
    if (!steps || steps.length === 0) {
      renderGrid(finalGrid);
      onDone();
      return;
    }
    var i = 0;
    function step() {
      if (i >= steps.length) {
        renderGrid(finalGrid);
        onDone();
        return;
      }
      var s   = steps[i++];
      resetCells();
      renderGrid(s.grid);
      setTimeout(function () {
        highlightCells(s.cells);
        dimNonWinning(s.cells);
        flashWinCells(s.cells);
        setTimeout(step, 700);
      }, 220);
    }
    step();
  }

  function hideWinPopup() {
    window.clearTimeout(winPopupTimer);
    winPopupTimer = null;
    if (winPopup) winPopup.classList.remove("is-visible");
  }

  /* A quiet floating receipt, reserved for wins worth interrupting for:
     a bonus, a long cascade chain, or a payout of five stakes or more.
     Ordinary wins already get the inline banner. */
  function showWinPopup(data) {
    var notable = Boolean(data.feature)
      || Number(data.cascades) >= 3
      || Number(data.payout) >= Number(data.stake) * 5;
    if (!winPopup || !data.win || !notable) {
      hideWinPopup();
      return;
    }

    winPopupLabel.textContent = data.feature
      ? "Heavenly Tribulation"
      : data.cascades > 1 ? "Cascade win" : "Win";
    winPopupAmount.textContent = "+" + money(data.payout) + " SS";

    var meta = [];
    if (data.cascades > 1) meta.push(data.cascades + " cascades");
    if (Number(data.favorBoost) > 0) {
      meta.push("Favor +" + Math.round(Number(data.favorBoost) * 100) + "%");
    }
    winPopupMeta.textContent = meta.join(" \u00b7 ");

    winPopup.classList.remove("is-visible");
    void winPopup.offsetWidth;
    winPopup.classList.add("is-visible");

    window.clearTimeout(winPopupTimer);
    winPopupTimer = window.setTimeout(hideWinPopup, 2600);
  }

  function showBanners(data) {
    if (data.win) {
      winBanner.classList.remove("hidden");
      lossBanner.classList.add("hidden");

      winLabel.textContent   = data.cascades > 1
        ? "Cascade Win ×" + data.cascades
        : data.feature ? "Bonus Win" : "Win";
      winAmount.textContent  = "+" + money(data.payout) + " SS";
      winMsg.textContent     = data.message;
      cascadeLabel.textContent = data.cascades > 1
        ? data.cascades + " cascades"
        : "";
      showWinPopup(data);
    } else {
      winBanner.classList.add("hidden");
      lossBanner.classList.remove("hidden");
      lossMsg.textContent = data.message;
      hideWinPopup();
    }

    /* Bounce-in animation */
    var banner = data.win ? winBanner : lossBanner;
    banner.classList.remove("result-pop");
    void banner.offsetWidth;
    banner.classList.add("result-pop");
  }

  function showFeature(feat) {
    if (!feat) {
      featurePanel.classList.add("hidden");
      bonusBar.classList.add("hidden");
      return;
    }
    featurePanel.classList.remove("hidden");
    bonusBar.classList.remove("hidden");
    bonusSpinsLeft.textContent = "0";
    bonusMult.textContent      = "×" + feat.bestMult.toFixed(1);
    featPlayed.textContent     = feat.played;
    featBestMult.textContent   = "×" + feat.bestMult.toFixed(1);
    featTotal.textContent      = "+" + money(feat.total) + " SS";
    featureOverlayText.textContent =
      feat.granted + " free spins were granted; " + feat.played +
      " were played. The Flying Sword stayed wild throughout, reaching ×" +
      feat.bestMult.toFixed(1) + ". Bonus payout: " + money(feat.total) + " SS.";
    featureOverlay.classList.remove("hidden");
    featureOverlay.classList.add("flex");
    closeFeatureOverlay.focus();
  }

  function prependRecent(data) {
    var list = document.getElementById("recentSpins");
    if (!list) return;
    var empty = list.querySelector("[data-empty]");
    if (empty) empty.remove();

    /* find the first symbol from first step */
    var key   = (data.steps && data.steps.length && data.steps[0].wins && data.steps[0].wins.length)
                ? data.steps[0].wins[0].key : "dao_emblem";
    var sym   = symMap[key] || {};
    var won   = data.win;

    var li = document.createElement("li");
    li.className = "flex items-center gap-3 rounded-lg border border-line/70 bg-ink-2/70 px-3 py-2 result-pop";
    var iconHtml = sym.icon
      ? '<img src="' + sym.icon + '" alt="" class="h-7 w-7 object-contain">'
      : '<span class="flex h-7 w-7 items-center justify-center text-sm font-bold text-mist-faint">\u25c6</span>';
    li.innerHTML = iconHtml
      + '<span class="min-w-0 flex-1 truncate text-sm text-mist">' + cfg.mode.name + '</span>'
      + '<span class="num text-xs ' + (won ? "text-jade" : "text-mist-faint") + '">'
      + (won ? "+" : "\u2212") + money(won ? data.payout : data.stake) + '</span>';
    list.insertBefore(li, list.firstChild);
    while (list.children.length > 8) list.removeChild(list.lastChild);
  }

  function doSpin() {
    if (state.spinning) return;
    var stake = Number(stakeInput.value) || 0;
    state.stake = stake;

    if (stake < cfg.mode.min || stake > cfg.mode.max) {
      toast("This table takes " + cfg.mode.min.toLocaleString() + " to " + cfg.mode.max.toLocaleString() + " SS.", true);
      stopAutoRoll("Auto-roll stopped: stake is outside this table's limits.");
      return;
    }
    if (stake > state.balance) {
      toast("Your Spatial Ring cannot cover that stake.", true);
      stopAutoRoll("Auto-roll stopped: balance cannot cover the next stake.");
      return;
    }

    state.spinning = true;
    state.currentAutoSpin = state.autoActive;
    setBusy(true);
    spinLabel.textContent = "Invoking…";
    winBanner.classList.add("hidden");
    lossBanner.classList.add("hidden");
    featurePanel.classList.add("hidden");
    bonusBar.classList.add("hidden");
    hideWinPopup();
    updatePips(0);
    eventAlert.classList.add("hidden");

    var spinStartedAt = Date.now();
    startSpinAnimation();

    fetch(cfg.spinUrl, {
      method: "POST",
      headers: {
        "Content-Type":  "application/json",
        "X-CSRFToken":   csrfMeta ? csrfMeta.content : ""
      },
      body: JSON.stringify({ mode: cfg.mode.slug, stake: stake })
    })
    .then(function (res) {
      return res.json().then(function (d) {
        if (!res.ok || !d.ok) throw new Error(d.error || "The mountain refused.");
        return d;
      });
    })
    .then(function (data) {
      var remainingRoll = Math.max(0, 1100 - (Date.now() - spinStartedAt));
      window.setTimeout(function () {
        stopSpinAnimation();
        if (data.steps && data.steps.length) {
          renderGrid(data.steps[0].grid);
        } else {
          renderGrid(data.grid);
        }
        updatePips(Math.min(data.scatters || 0, 4));

        playCascades(data.steps, data.grid, function () {
          state.balance = Number(data.balance);
          state.favor   = Number(data.fortuneFavor);
          paintWallet();
          showBanners(data);
          showFeature(data.feature);
          var notableEvent = showEventAlerts(data);
          prependRecent(data);

          state.spinning = false;
          setBusy(false);
          spinLabel.textContent = "Invoke the Grid";

          if (state.currentAutoSpin) state.autoRemaining -= 1;
          state.currentAutoSpin = false;
          if (state.autoActive && state.autoRemaining <= 0) {
            stopAutoRoll("Auto-roll finished its selected spin limit.");
          } else if (state.autoActive && notableEvent) {
            stopAutoRoll("Auto-roll paused so you can review the scatter, feature, or high-tier alert.");
          } else if (state.autoActive) {
            autoRollStatus.textContent = "Auto-roll active: " + state.autoRemaining + " spins remaining.";
            state.autoTimer = window.setTimeout(doSpin, 500);
          }
        });
      }, remainingRoll);
    })
    .catch(function (err) {
      stopSpinAnimation();
      state.spinning = false;
      setBusy(false);
      spinLabel.textContent = "Invoke the Grid";
      state.currentAutoSpin = false;
      stopAutoRoll("Auto-roll stopped because the spin request failed.");
      toast(err.message || "Something went wrong.", true);
    });
  }

  /* ──────────────── wiring ──────────────── */

  spinBtn.addEventListener("click", doSpin);
  autoRollBtn.addEventListener("click", function () {
    if (state.autoActive) {
      stopAutoRoll("Auto-roll stopped. The current spin, if any, will finish.");
    } else {
      startAutoRoll();
    }
  });
  closeFeatureOverlay.addEventListener("click", function () {
    featureOverlay.classList.add("hidden");
    featureOverlay.classList.remove("flex");
    spinBtn.focus();
  });

  document.querySelectorAll("[data-stake]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      stakeInput.value = btn.dataset.stake;
      state.stake = Number(btn.dataset.stake);
      paintPotential();
    });
  });

  stakeInput.addEventListener("input", function () {
    state.stake = Number(stakeInput.value) || 0;
    paintPotential();
  });

  /* The idle grid is a preview, not a spin result; show the full symbol set. */
  var previewSymbols = [];
  while (previewSymbols.length < 30) {
    cfg.symbols.forEach(function (symbol) { previewSymbols.push(symbol.key); });
  }
  previewSymbols = previewSymbols.slice(0, 30);
  for (var i = previewSymbols.length - 1; i > 0; i--) {
    var j = Math.floor(Math.random() * (i + 1));
    var key = previewSymbols[i];
    previewSymbols[i] = previewSymbols[j];
    previewSymbols[j] = key;
  }
  renderGrid(previewSymbols);
  syncAutoControls();
  paintWallet();
  paintPotential();

})();
