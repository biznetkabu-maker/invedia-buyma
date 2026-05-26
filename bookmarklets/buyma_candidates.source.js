/**
 * BUYMA — 画面上の一覧・ランキング・検索から「商品詳細 URL」の候補を抽出して一覧化する。
 *
 * 【役割】
 *   • 自動取得はユーザーと同じブラウザコンテキスト（描画済みDOM）から行うので、
 *     ヘッドレス Playwright と比べてブロックを受けにくいことがある。
 *   • 「どれが仕入検討用か」の最終判断は人手（チェックの付け外し → コピー）。
 *
 * 【制限】
 *   • BUYMA の DOM / JSON-LD が変わると壊れる（恒久的にはメンテ要）。
 *   • 一覧に混ざるリンクのみ取得。SKU の正しさ・同一モデル確認は別途ユーザーが行うこと。
 *
 * 使い方: bookmarklets/README.md の手順でブックマークに登録し、対象ページで実行。
 */
(function () {
  "use strict";

  /** インストール確認用（v3-panel-import = 自動スクロール + 白パネル取込） */
  var BOOKMARKLET_VERSION = "v3-panel-import";
  /** 白パネル → シート取込（2_候補_取込_サーバー起動.bat が起動していること） */
  var LOCAL_IMPORT_BASE = "http://127.0.0.1:18765";

  /* パネルを閉じたあと再実行できるよう、UI が無いときはフラグをリセット */
  if (
    window.__BUYMA_CANDIDATE_EXTRACTOR__ &&
    document.getElementById("buyma-candidate-extractor-ui")
  ) {
    return;
  }
  window.__BUYMA_CANDIDATE_EXTRACTOR__ = BOOKMARKLET_VERSION;

  /** 予期しないエラーでもユーザーに伝える（無言失敗を防ぐ） */
  try {
    main();
  } catch (err) {
    var msg = err && err.message ? err.message : String(err);
    alert("BUYMA候補抽出でエラーが発生しました。\n\n" + msg);
  }

  function main() {
  /**
   * optional catch は ES2019。Safari 等旧環境ではブックマークレット全体がパースエラーになるため catch(e) を使う。
   */

  if (!/(^|\.)buyma\.com$/i.test(location.hostname)) {
    alert("BUYMA（*.buyma.com）のページで実行してください。\n現在: " + location.hostname);
    return;
  }

  /** 二重実行時に古いオーバーレイを除去 */
  var old = document.getElementById("buyma-candidate-extractor-ui");
  if (old && old.parentNode) old.parentNode.removeChild(old);

  function walkJsonLd(products, obj, depth) {
    if (!obj || typeof obj !== "object" || depth > 12) return;
    var t = obj["@type"];
    var types = Array.isArray(t) ? t : t ? [t] : [];
    if (types.indexOf("Product") >= 0 && obj.url) {
      var priceGuess = "";
      var off = obj.offers;
      if (off) {
        var offer = Array.isArray(off) ? off[0] : off;
        if (offer && offer.price !== undefined && offer.price !== null) {
          priceGuess = String(offer.price).replace(/[^\d]/g, "");
        }
      }
      products.push({
        url: String(obj.url),
        title: String(obj.name || obj.description || ""),
        priceGuess: priceGuess,
        source: "json-ld",
      });
    }
    if (types.indexOf("ItemList") >= 0 && Array.isArray(obj.itemListElement)) {
      obj.itemListElement.forEach(function (el) {
        var item = el && el.item !== undefined ? el.item : el;
        walkJsonLd(products, item, depth + 1);
      });
    }
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (Array.isArray(v))
        v.forEach(function (x) {
          walkJsonLd(products, x, depth + 1);
        });
      else if (typeof v === "object") walkJsonLd(products, v, depth + 1);
    });
  }

  function parseJsonLdProducts() {
    var out = [];
    var scripts = document.querySelectorAll(
      'script[type="application/ld+json"]'
    );
    scripts.forEach(function (s) {
      try {
        var d = JSON.parse(s.textContent);
        var list = Array.isArray(d) ? d : [d];
        list.forEach(function (x) {
          var graphs = x && x["@graph"] !== undefined ? x["@graph"] : [x];
          graphs.forEach(function (g) {
            walkJsonLd(out, g, 0);
          });
        });
      } catch (e) {
        /* ignore */
      }
    });
    return out;
  }

  function itemDigits(href) {
    if (!href) return null;
    var u;
    try {
      u = new URL(href, location.href).href;
    } catch (e) {
      return null;
    }
    /** BUYMA 商品IDは桁数が変わりうるため 4桁以上を許容（誤判定は pathname で軽減） */
    var m = u.match(/\/(?:item|items)\/(\d{4,})\b/i);
    return m ? m[1] : null;
  }

  function canonItemUrl(id) {
    return "https://www.buyma.com/item/" + id + "/";
  }

  function pushPrice(out, raw) {
    var n = parseInt(String(raw).replace(/[^\d]/g, ""), 10);
    if (n >= 1000 && n <= 10000000) out.push(n);
  }

  /** カード内テキストから価格らしい数値を抽出 */
  function parseJpyPrices(text) {
    var out = [];
    var src = text || "";
    var patterns = [
      /[¥￥]\s*([\d,]+)/g,
      /([\d,]+)\s*円/g,
      /([1-9][\d,]{2,})\s*\d{1,2}\s*%?\s*OFF/gi,
    ];
    patterns.forEach(function (re) {
      var m;
      while ((m = re.exec(src)) !== null) {
        pushPrice(out, m[1]);
      }
    });
    return out;
  }

  /**
   * 複数価格があるカードは小さい方をセール価格とみなす（例: ¥108,000 / ¥59,800）。
   * 1件だけならその値。取れなければ空文字。
   */
  function guessSalePrice(prices) {
    if (!prices || !prices.length) return "";
    var min = prices[0];
    for (var i = 1; i < prices.length; i++) {
      if (prices[i] < min) min = prices[i];
    }
    return String(min);
  }

  var CARD_CLOSEST = [
    "li",
    "article",
    "[class*='ItemCard']",
    "[class*='item_card']",
    "[class*='item-card']",
    "[class*='ItemListItem']",
    "[class*='item-list-item']",
    "[class*='product-item']",
    "[class*='ProductItem']",
    "[class*='search-item']",
    "[data-item-id]",
    "tr",
  ];

  function pricesInElement(el) {
    if (!el) return [];
    var merged = [];
    parseJpyPrices(el.innerText || "").forEach(function (n) {
      merged.push(n);
    });
    parseJpyPrices(el.textContent || "").forEach(function (n) {
      merged.push(n);
    });
    try {
      el.querySelectorAll(
        "[class*='price'], [class*='Price'], [class*='tanka'], [class*='Tanka'], [data-price], [data-tanka]"
      ).forEach(function (node) {
        var dp =
          node.getAttribute("data-price") ||
          node.getAttribute("data-tanka") ||
          node.getAttribute("data-item-price") ||
          "";
        if (dp) pushPrice(merged, dp);
        parseJpyPrices(node.textContent || "").forEach(function (n) {
          merged.push(n);
        });
      });
    } catch (e) {
      /* ignore */
    }
    return merged;
  }

  function scoreCard(card, prices) {
    if (!prices.length) return -1;
    var links = 0;
    try {
      links = card.querySelectorAll('a[href*="/item/"]').length;
    } catch (e2) {
      links = 99;
    }
    var len = (card.innerText || "").length;
    var score = 0;
    if (links <= 1) score += 40;
    else if (links <= 3) score += 25;
    else if (links > 8) return -1;
    if (prices.length >= 2) score += 25;
    if (prices.length === 1) score += 10;
    if (len > 0 && len < 400) score += 20;
    else if (len < 800) score += 10;
    else if (len > 2500) score -= 30;
    return score;
  }

  /** 商品リンク付近のカードから価格を推定 */
  function priceFromCard(anchor) {
    var bestPrices = [];
    var bestScore = -1;
    var s;
    for (s = 0; s < CARD_CLOSEST.length; s++) {
      var card = null;
      try {
        card = anchor.closest && anchor.closest(CARD_CLOSEST[s]);
      } catch (e) {
        card = null;
      }
      if (!card || card === document.body || card === document.documentElement)
        continue;
      var p = pricesInElement(card);
      var sc = scoreCard(card, p);
      if (sc > bestScore) {
        bestScore = sc;
        bestPrices = p;
      }
    }
    if (bestPrices.length) return guessSalePrice(bestPrices);

    var el = anchor;
    var walkBest = [];
    var walkScore = -1;
    for (var depth = 0; depth < 16 && el; depth++) {
      var p2 = pricesInElement(el);
      var sc2 = scoreCard(el, p2);
      if (sc2 > walkScore) {
        walkScore = sc2;
        walkBest = p2;
      }
      el = el.parentElement;
    }
    return guessSalePrice(walkBest);
  }

  /** ページ内 script / JSON に埋まった tanka を item_id で探す */
  function priceFromEmbeddedJson(itemId) {
    var id = String(itemId);
    /** 単一引用で包む（二重引用だと minify 後に "tanka" で文字列が切れ SyntaxError になる） */
    var tankaTail = '"?[\\s\\S]{0,1200}?"tanka"\\s*:\\s*"?([0-9]+)"?';
    var patterns = [
      new RegExp('"item_id"\\s*:\\s*"?'.concat(id, tankaTail), "i"),
      new RegExp('"itemId"\\s*:\\s*"?'.concat(id, tankaTail), "i"),
      new RegExp("/item/".concat(id, tankaTail), "i"),
    ];
    var scripts = document.querySelectorAll("script");
    for (var i = 0; i < scripts.length; i++) {
      var t = scripts[i].textContent || "";
      if (t.indexOf(id) < 0) continue;
      for (var j = 0; j < patterns.length; j++) {
        var m = t.match(patterns[j]);
        if (m && m[1]) return m[1];
      }
    }
    return "";
  }

  function queryItemAnchors(itemId) {
    var sel = 'a[href*="/item/'.concat(itemId, '"]');
    var found = [];
    function scan(root) {
      if (!root || !root.querySelectorAll) return;
      root.querySelectorAll(sel).forEach(function (a) {
        found.push(a);
      });
      root.querySelectorAll("*").forEach(function (el) {
        if (el.shadowRoot) scan(el.shadowRoot);
      });
    }
    scan(document);
    return found;
  }

  /** 全 item について価格を補完（複数アンカー・埋め込み JSON） */
  function enrichItemPrices(byId) {
    Object.keys(byId).forEach(function (id) {
      if (byId[id].price_guess) return;
      var fromJson = priceFromEmbeddedJson(id);
      if (fromJson) {
        upsert(byId, id, "", "embed-tanka", fromJson);
        return;
      }
      var best = "";
      queryItemAnchors(id).forEach(function (a) {
        var p = priceFromCard(a);
        if (p && (!best || parseInt(p, 10) < parseInt(best, 10))) best = p;
      });
      if (best) upsert(byId, id, "", "price-card", best);
    });
  }

  /** すべての a[href] を走査（href が完全URLのみ・相対のみ混在・SPA に強くする） */
  function collectAnchors(byId, titleGuess) {
    function scan(root) {
      if (!root || !root.querySelectorAll) return;
      root.querySelectorAll("a[href]").forEach(function (a) {
        var id = itemDigits(a.getAttribute("href"));
        if (!id) return;
        var title = (
          titleGuess(a.textContent || "") ||
          (a.getAttribute("title") || "").trim()
        ).replace(/\s+/g, " ");
        var priceGuess = priceFromCard(a);
        upsert(byId, id, title || "", "anchor", priceGuess);
      });
    }
    scan(document);
    /** open な Shadow DOM 内のリンクも試す（Web Components 対策） */
    document.querySelectorAll("*").forEach(function (el) {
      if (el.shadowRoot) scan(el.shadowRoot);
    });
  }

  function titleGuess(txt) {
    var t = (txt || "").replace(/\s+/g, " ").trim();
    if (t.length < 3 || t.length > 200) return "";
    var bad = /^[\d\s¥￥,:]+$/;
    if (bad.test(t)) return "";
    return t;
  }

  function upsert(byId, id, title, source, priceGuess) {
    if (!byId[id]) {
      byId[id] = {
        checked: true,
        buyma_url: canonItemUrl(id),
        title: "",
        price_guess: "",
        sources: [],
      };
    }
    if (title && title.length > (byId[id].title || "").length)
      byId[id].title = title;
    if (priceGuess) {
      var cur = byId[id].price_guess;
      if (
        !cur ||
        (parseInt(priceGuess, 10) > 0 &&
          parseInt(priceGuess, 10) < parseInt(cur, 10))
      ) {
        byId[id].price_guess = priceGuess;
      }
    }
    if (byId[id].sources.indexOf(source) < 0) byId[id].sources.push(source);
  }

  function normalizeFromLd(ldList, byId) {
    ldList.forEach(function (x) {
      var id = itemDigits(x.url);
      if (!id) return;
      upsert(
        byId,
        id,
        titleGuess(x.title) || "",
        "jsonld",
        x.priceGuess || ""
      );
    });
  }

  /** JSON がネスト複雑で Product を取り逃すとき用 */
  function regexIdsFromLdScripts(byId) {
    document
      .querySelectorAll('script[type="application/ld+json"]')
      .forEach(function (s) {
        var t = s.textContent || "";
        var re = /buyma\.com\/item\/(\d{4,})\b/gi;
        var m;
        while ((m = re.exec(t)) !== null) {
          upsert(byId, m[1], "", "jsonld-regex", "");
        }
      });
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function countItemLinks() {
    return document.querySelectorAll('a[href*="/item/"]').length;
  }

  /** 無限スクロール一覧を下まで自動スクロールして遅延読み込みを促す */
  function autoScrollListing(onProgress) {
    var maxSteps = 55;
    var stallLimit = 4;
    var lastHeight = 0;
    var lastCount = countItemLinks();
    var stall = 0;
    var step = 0;

    function nudgeScroll() {
      var delta = Math.max(400, Math.floor(window.innerHeight * 0.82));
      window.scrollBy(0, delta);
      try {
        document.querySelectorAll("main, [role='main']").forEach(function (el) {
          if (el.scrollHeight > el.clientHeight + 40) {
            el.scrollTop = el.scrollHeight;
          }
        });
      } catch (e) {
        /* ignore */
      }
      window.scrollTo(0, document.documentElement.scrollHeight);
    }

    return new Promise(function (resolve) {
      function tick() {
        step += 1;
        nudgeScroll();
        var h = document.documentElement.scrollHeight;
        var n = countItemLinks();
        if (onProgress) onProgress(step, n, stall);
        if (n > lastCount || h > lastHeight + 40) {
          stall = 0;
        } else {
          stall += 1;
        }
        lastCount = n;
        lastHeight = h;
        var atBottom =
          window.scrollY + window.innerHeight >= h - 100;
        if (stall >= stallLimit || step >= maxSteps || atBottom) {
          window.scrollTo(0, 0);
          resolve({ steps: step, itemLinks: n });
          return;
        }
        sleep(480).then(tick);
      }
      nudgeScroll();
      sleep(520).then(tick);
    });
  }

  var scrollOverlay = null;
  function showScrollOverlay() {
    scrollOverlay = document.createElement("div");
    scrollOverlay.id = "buyma-candidate-scroll-ui";
    scrollOverlay.setAttribute(
      "style",
      "position:fixed;inset:0;z-index:2147483646;background:rgba(0,0,0,.35);" +
        "display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;"
    );
    var box = document.createElement("div");
    box.setAttribute(
      "style",
      "background:#fff;padding:20px 28px;border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,.25);text-align:center;max-width:90vw;"
    );
    box.innerHTML =
      "<div style='font-size:16px;font-weight:600;margin-bottom:8px'>一覧を自動スクロール中</div>" +
      "<div id='buyma-scroll-status' style='font-size:13px;color:#444'>読み込みを待っています…</div>" +
      "<div style='font-size:12px;color:#888;margin-top:10px'>そのままお待ちください（最大約30秒）</div>";
    scrollOverlay.appendChild(box);
    document.body.appendChild(scrollOverlay);
  }

  function updateScrollOverlay(step, linkCount) {
    var el = document.getElementById("buyma-scroll-status");
    if (el) {
      el.textContent =
        "スクロール " + step + " 回目 · 商品リンク約 " + linkCount + " 件";
    }
  }

  function removeScrollOverlay() {
    if (scrollOverlay && scrollOverlay.parentNode) {
      scrollOverlay.parentNode.removeChild(scrollOverlay);
    }
    scrollOverlay = null;
  }

  function runExtractionAndPanel() {
  var byId = {};
  normalizeFromLd(parseJsonLdProducts(), byId);
  regexIdsFromLdScripts(byId);
  collectAnchors(byId, titleGuess);
  enrichItemPrices(byId);

  var rows = Object.keys(byId)
    .map(function (id) {
      return byId[id];
    })
    .sort(function (a, b) {
      return a.buyma_url.localeCompare(b.buyma_url);
    });
  var priceFilled = rows.filter(function (r) {
    return r.price_guess;
  }).length;

  if (!rows.length) {
    alert(
      "このページから商品リンク（ /item/<数字>/ ）が見つかりませんでした。\nランキング・検索結果を表示した状態でもう一度試してください。"
    );
    return;
  }

  var wrap = document.createElement("div");
  wrap.id = "buyma-candidate-extractor-ui";
  wrap.setAttribute(
    "style",
    "position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.45);" +
      "display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;font-family:system-ui,sans-serif;"
  );
  var box = document.createElement("div");
  box.setAttribute(
    "style",
    "background:#fff;color:#111;max-width:920px;width:100%;max-height:90vh;" +
      "overflow:auto;border-radius:10px;padding:16px;box-shadow:0 8px 32px rgba(0,0,0,.3);"
  );

  var h = document.createElement("h2");
  h.textContent =
    "BUYMA 候補抽出 " +
    BOOKMARKLET_VERSION +
    "（" +
    rows.length +
    "件・価格推定 " +
    priceFilled +
    "件）";
  h.setAttribute("style", "margin:0 0 8px;font-size:18px;");
  var sub = document.createElement("p");
  sub.setAttribute("style", "margin:0 0 12px;font-size:13px;color:#444;");
  sub.textContent =
    "不要な行のチェックを外してからコピーしてください。一覧表示価格（推定）は参考用。本番の売価は intake で確定。URL・同一商品は必ず人手で確認。" +
    (priceFilled === 0
      ? " ※価格が0件のときは一覧の読み込みが足りない可能性があります。もう一度実行してください。"
      : "");

  var tb = document.createElement("table");
  tb.setAttribute(
    "style",
    "width:100%;border-collapse:collapse;font-size:12px;margin-bottom:12px;"
  );
  var thead = document.createElement("tr");
  ["", "商品URL", "タイトル推定", "価格推定", "取得元"].forEach(function (lab) {
    var th = document.createElement("th");
    th.textContent = lab;
    th.setAttribute(
      "style",
      "text-align:left;border-bottom:1px solid #ccc;padding:6px 4px;"
    );
    thead.appendChild(th);
  });
  tb.appendChild(thead);

  rows.forEach(function (row) {
    var tr = document.createElement("tr");
    var td0 = document.createElement("td");
    var chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = true;
    row._chk = chk;
    td0.appendChild(chk);
    td0.setAttribute(
      "style",
      "border-bottom:1px solid #eee;padding:6px 4px;width:36px;"
    );
    function td(txt, mono) {
      var t = document.createElement("td");
      t.textContent = txt || "";
      t.setAttribute(
        "style",
        "border-bottom:1px solid #eee;padding:6px 4px;" +
          (mono ? "word-break:break-all;font-family:ui-monospace,monospace;" : "")
      );
      return t;
    }
    tr.appendChild(td0);
    tr.appendChild(td(row.buyma_url, true));
    tr.appendChild(td(row.title));
    tr.appendChild(
      td(row.price_guess ? "¥" + Number(row.price_guess).toLocaleString("ja-JP") : "")
    );
    tr.appendChild(td(row.sources.join(",")));
    tb.appendChild(tr);
  });

  var ta = document.createElement("textarea");
  ta.setAttribute(
    "style",
    "width:100%;height:140px;font-size:12px;font-family:ui-monospace,monospace;"
  );

  function buildTsv(includeUnchecked) {
    var lines = [
      [
        "buyma_url",
        "title_guess",
        "list_page_url",
        "price_guess_jpy",
        "extractor_note",
      ].join("\t"),
    ];
    rows.forEach(function (row) {
      if (!includeUnchecked && !row._chk.checked) return;
      lines.push(
        [
          row.buyma_url,
          (row.title || "").replace(/\t/g, " "),
          location.href.replace(/\t/g, " "),
          (row.price_guess || "").replace(/\t/g, " "),
          row.price_guess
            ? "bookmarklet_list_price_guess"
            : "bookmarklet_human_verified_needed",
        ].join("\t")
      );
    });
    return lines.join("\n");
  }

  function refreshPreview() {
    ta.value = buildTsv(false);
  }

  rows.forEach(function (row) {
    row._chk.addEventListener("change", refreshPreview);
  });

  refreshPreview();

  var importStatus = document.createElement("p");
  importStatus.id = "buyma-import-status";
  importStatus.setAttribute(
    "style",
    "margin:0 0 10px;font-size:12px;color:#666;min-height:1.2em;"
  );
  importStatus.textContent = "取込サーバー: 確認中…";

  function setImportStatus(text, color) {
    importStatus.textContent = text;
    if (color) importStatus.style.color = color;
  }

  function pingImportServer(cb) {
    fetch(LOCAL_IMPORT_BASE + "/health", { method: "GET", mode: "cors" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        cb(!!(d && d.ok));
      })
      .catch(function () {
        cb(false);
      });
  }

  pingImportServer(function (up) {
    if (up) {
      setImportStatus(
        "取込サーバー: 起動中（白パネルからシートに取込できます）",
        "#059669"
      );
    } else {
      setImportStatus(
        "取込サーバー: 未起動 → 2_候補_取込_サーバー起動.bat を実行してください",
        "#b45309"
      );
    }
  });

  function postTsvToSheet(tsv, done) {
    fetch(LOCAL_IMPORT_BASE + "/import", {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: tsv,
    })
      .then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, data: d };
        });
      })
      .then(function (res) {
        done(null, res);
      })
      .catch(function (err) {
        done(err, null);
      });
  }

  var btnRow = document.createElement("div");
  btnRow.setAttribute("style", "display:flex;flex-wrap:wrap;gap:8px;");
  function btn(label, bg, fn) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.setAttribute(
      "style",
      "cursor:pointer;padding:8px 14px;border:none;border-radius:6px;color:#fff;background:" +
        bg +
        ";font-size:14px;"
    );
    b.addEventListener("click", fn);
    return b;
  }
  btnRow.appendChild(
    btn("シートに取込", "#059669", function () {
      var text = buildTsv(false);
      refreshPreview();
      if (!text || text.indexOf("buyma_url") < 0) {
        alert("取り込む TSV がありません。商品にチェックが付いているか確認してください。");
        return;
      }
      setImportStatus("シートへ送信中…", "#444");
      postTsvToSheet(text, function (err, res) {
        if (err || !res) {
          setImportStatus(
            "取込失敗: サーバー未起動の可能性 → 2_候補_取込_サーバー起動.bat",
            "#dc2626"
          );
          alert(
            "シートへの取込に失敗しました。\n\n" +
              "2_候補_取込_サーバー起動.bat を実行してから、もう一度お試しください。\n\n" +
              (err && err.message ? err.message : "接続できませんでした")
          );
          pingImportServer(function (up) {
            if (!up) return;
            setImportStatus("取込サーバー: 起動中", "#059669");
          });
          return;
        }
        var d = res.data || {};
        if (res.ok && d.ok) {
          setImportStatus(
            "取込完了: 追加 " +
              (d.added || 0) +
              " 件 / スキップ " +
              (d.skipped || 0) +
              " 件",
            "#059669"
          );
          alert(
            "シートに取り込みました。\n\n" +
              (d.message || "") +
              (d.worksheet ? "\nシート: " + d.worksheet : "")
          );
        } else {
          setImportStatus("取込失敗: " + (d.message || "不明"), "#dc2626");
          alert("取込できませんでした。\n\n" + (d.message || "TSV を確認してください。"));
        }
      });
    })
  );
  btnRow.appendChild(
    btn("TSV をコピー（チェック済みのみ）", "#2563eb", function () {
      var text = buildTsv(false);
      refreshPreview();
      function fallbackCopy() {
        ta.focus();
        ta.select();
        try {
          document.execCommand("copy");
          alert("クリップボードにコピーしました。");
        } catch (e2) {
          alert(
            "コピーに失敗しました。下のテキストを手動で選択してコピーしてください。"
          );
        }
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          alert("クリップボードにコピーしました。");
        }).catch(function () {
          fallbackCopy();
        });
      } else {
        fallbackCopy();
      }
    })
  );
  btnRow.appendChild(
    btn("プレビュー更新", "#64748b", function () {
      refreshPreview();
    })
  );
    btnRow.appendChild(
      btn("閉じる", "#334155", function () {
        document.body.removeChild(wrap);
        try {
          delete window.__BUYMA_CANDIDATE_EXTRACTOR__;
        } catch (e) {
          window.__BUYMA_CANDIDATE_EXTRACTOR__ = undefined;
        }
      })
    );

  box.appendChild(h);
  box.appendChild(sub);
  box.appendChild(importStatus);
  box.appendChild(tb);
  box.appendChild(ta);
  box.appendChild(btnRow);
  wrap.appendChild(box);
  document.body.appendChild(wrap);
  }

  showScrollOverlay();
  autoScrollListing(updateScrollOverlay)
    .then(function () {
      removeScrollOverlay();
      runExtractionAndPanel();
    })
    .catch(function (err) {
      removeScrollOverlay();
      var scrollErr = err && err.message ? err.message : String(err);
      alert("自動スクロール中にエラーが発生しました。\n\n" + scrollErr);
    });
  } /* end main */
})();
