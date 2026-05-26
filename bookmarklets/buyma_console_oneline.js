/** BUYMA 一覧ページの Console に貼る 1 行（先頭から末尾まで全部） */
fetch("https://raw.githubusercontent.com/biznetkabu-maker/invedia-automation/main/bookmarklets/buyma_candidates.run.js?t=" + Date.now())
  .then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.text();
  })
  .then(function (t) {
    eval(t);
  })
  .catch(function (e) {
    alert("BUYMA候補の読込に失敗しました。\n" + (e && e.message ? e.message : e));
  });
