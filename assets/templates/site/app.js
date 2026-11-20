/* BirdTrace 静态图库站 · 前端(无框架)
   数据: gallery.js 注入 window.G / window.L; 图片两档 256/1280 webp。
   规范 §4.5-§4.10: 卡片网格/筛选胶囊/详情/懒加载/固定比例占位/失败占位。 */
(function () {
  "use strict";
  var G = window.G || { meta: {}, species: [], months: [], regions: [],
    tags: [], collections: [] };
  var L = window.L || {};

  function esc(s) {
    return (s == null ? "" : String(s)).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
        "'": "&#39;" }[c];
    });
  }
  function img(h, size) { return "images/" + h + "." + size + ".webp"; }
  function speciesUrl(code) {
    return "species.html?code=" + encodeURIComponent(code);
  }
  window.imgErr = function (im) {
    im.classList.add("missing");
    if (im.parentElement) im.parentElement.classList.add("miss");
  };
  function phImg(h, size, alt, cls) {
    return '<img ' + (cls ? 'class="' + cls + '" ' : "") +
      'loading="lazy" decoding="async" src="' + img(h, size) +
      '" alt="' + esc(alt) + '" onerror="imgErr(this)">';
  }
  function nPhotos(n) {
    return n + " " + (L.unit || L.photos || "");
  }

  /* ---------- 卡片 ---------- */
  function card(s) {
    var sub = [nPhotos(s.count)];
    if (s.region) sub.push(s.region);
    return '<a class="card" href="' + speciesUrl(s.code) + '">' +
      '<div class="ph">' + phImg(s.best, 256, s.cn) + "</div>" +
      '<div class="cap"><div class="cn">' + esc(s.cn) + "</div>" +
      (s.en ? '<div class="en">' + esc(s.en) + "</div>" : "") +
      '<div class="n">' + esc(sub.join(" · ")) + "</div></div></a>";
  }

  /* ---------- 首页: 精选 ---------- */
  function renderFeatured() {
    var host = document.getElementById("featured");
    if (!host) return;
    var list = G.species.slice(0, 12);
    host.innerHTML = list.length
      ? list.map(card).join("")
      : '<div class="empty">' + esc(L.emptySpecies || "") + "</div>";
  }

  /* ---------- 首页: 最近更新 ---------- */
  function renderRecent() {
    var host = document.getElementById("recent");
    if (!host) return;
    var months = G.months.slice().reverse().slice(0, 3);
    if (!months.length) {
      host.innerHTML = '<div class="empty">' + esc(L.emptyMonths || "") +
        "</div>";
      return;
    }
    host.innerHTML = months.map(function (m) {
      var ph = (m.photos || []).map(function (p) {
        return '<div class="ph" style="width:86px;height:64px">' +
          phImg(p.h, 256, p.cn || m.ym) + "</div>";
      }).join("");
      return '<a class="entry" href="timeline.html">' + ph +
        "<div><b>" + esc(m.ym) + "</b><span>" + esc(nPhotos(m.n)) +
        "</span></div></a>";
    }).join("");
  }

  /* ---------- 图鉴: 筛选 ---------- */
  var F = { r: "", y: "", q: "", grp: "" };
  try {
    F.r = new URLSearchParams(location.search).get("r") || "";
  } catch (e) {}

  function renderGallery() {
    var host = document.getElementById("grid");
    if (!host) return;
    var chips = document.getElementById("chips");
    if (chips && !chips.dataset.ready) {
      chips.dataset.ready = "1";
      var regions = [];
      G.species.forEach(function (s) {
        if (s.region && regions.indexOf(s.region) < 0) regions.push(s.region);
      });
      var html = '<button class="chip' + (F.r ? "" : " on") +
        '" data-r="">' + esc(L.all || "") + "</button>";
      regions.forEach(function (r) {
        html += '<button class="chip' + (F.r === r ? " on" : "") +
          '" data-r="' + esc(r) + '">' + esc(r) + "</button>";
      });
      chips.innerHTML = html;
      chips.addEventListener("click", function (e) {
        var b = e.target.closest(".chip");
        if (!b) return;
        F.r = b.getAttribute("data-r") || "";
        var inp = document.getElementById("q");
        F.q = (inp && inp.value || "").trim().toLowerCase();
        Array.prototype.forEach.call(chips.children, function (c) {
          c.classList.toggle("on", c === b);
        });
        paint();
      });
    }
    var gch = document.getElementById("gchips");
    if (gch && !gch.dataset.ready) {
      gch.dataset.ready = "1";
      var groups = [];
      (G.tags || []).forEach(function (t) {
        groups.push({ key: "tag:" + t.name, label: t.name, n: t.photos.length });
      });
      (G.collections || []).forEach(function (c) {
        groups.push({ key: "col:" + c.name, label: c.name,
          n: c.photos.length });
      });
      if (groups.length) {
        gch.innerHTML = '<span class="n" style="font-size:11px;color:var(--ink3)">'
          + esc(L.groups || "") + "</span>" + groups.map(function (g) {
            return '<button class="chip' + (F.grp === g.key ? " on" : "") +
              '" data-g="' + esc(g.key) + '">' + esc(g.label) + " · " +
              g.n + "</button>";
          }).join("");
        gch.addEventListener("click", function (e) {
          var b = e.target.closest(".chip");
          if (!b) return;
          var k = b.getAttribute("data-g") || "";
          F.grp = F.grp === k ? "" : k;
          Array.prototype.forEach.call(gch.querySelectorAll(".chip"), function (c) {
            c.classList.toggle("on", c.getAttribute("data-g") === F.grp);
          });
          paint();
        });
      } else {
        gch.style.display = "none";
      }
    }
    var q = document.getElementById("q");
    if (q && !q.dataset.ready) {
      q.dataset.ready = "1";
      q.addEventListener("input", function () {
        F.q = (q.value || "").trim().toLowerCase();
        paint();
      });
    }
    paint();

    function paint() {
      if (F.grp) {
        var g = null;
        (G.tags || []).forEach(function (t) {
          if ("tag:" + t.name === F.grp) g = t;
        });
        (G.collections || []).forEach(function (c) {
          if ("col:" + c.name === F.grp) g = c;
        });
        var ps = (g && g.photos) || [];
        host.innerHTML = ps.length ? ps.map(function (p) {
          return '<div class="card"><div class="ph">' + phImg(p.h, 256, p.cn) +
            '</div><div class="cap"><div class="cn">' + esc(p.cn || "") +
            "</div></div></div>";
        }).join("") : '<div class="empty">' + esc(L.emptySearch || "") +
          "</div>";
        var n0 = document.getElementById("count");
        if (n0) n0.textContent = ps.length + " " + (L.unit || "");
        return;
      }
      var list = G.species.filter(function (s) {
        if (F.r && s.region !== F.r) return false;
        if (!F.q) return true;
        return (s.cn + " " + (s.en || "") + " " + (s.code || ""))
          .toLowerCase().indexOf(F.q) >= 0;
      });
      host.innerHTML = list.length ? list.map(card).join("")
        : '<div class="empty">' + esc(L.emptySearch || "") + "</div>";
      var n = document.getElementById("count");
      if (n) {
        n.textContent = list.length + " / " + G.species.length + " " +
          (L.species || "");
      }
    }
  }

  /* ---------- 详情 ---------- */
  function renderDetail() {
    var host = document.getElementById("detail");
    if (!host) return;
    var code = new URLSearchParams(location.search).get("code") || "";
    var s = null;
    for (var i = 0; i < G.species.length; i++) {
      if (G.species[i].code === code) { s = G.species[i]; break; }
    }
    if (!s) {
      host.innerHTML = '<div class="empty">' + esc(L.emptySpecies || "") +
        "</div>";
      return;
    }
    document.title = s.cn + " · BirdTrace";
    var months = s.months || [];
    var mx = Math.max.apply(null, months.concat([1]));
    var bars = months.map(function (v) {
      var h = Math.max(3, Math.round(v / mx * 78));
      return '<i class="' + (v ? "" : "z") + '" style="height:' + h +
        'px" title="' + v + '"></i>';
    }).join("");
    var ruler = months.map(function (_v, i) {
      return "<span>" + (i + 1) + "</span>";
    }).join("");
    var metaRows = [
      [L.count, nPhotos(s.count)],
      [L.firstLast, (s.first || "—") + " · " + (s.last || "—")],
      [L.region, s.region || "—"],
    ].map(function (r) {
      return '<div class="mrow"><span>' + esc(r[0]) + "</span><b>" +
        esc(r[1]) + "</b></div>";
    }).join("");
    var rel = (s.photos || []).slice(0, 12).map(function (p) {
      return '<div class="ph" style="border-radius:12px;overflow:hidden;' +
        'aspect-ratio:1/1">' + phImg(p.h, 256, s.cn) + "</div>";
    }).join("");
    host.innerHTML =
      '<div class="crumb"><a href="gallery.html">‹ ' + esc(L.gallery || "") +
      "</a>　/　" + esc(s.cn) + "</div>" +
      '<div class="detail"><div class="big">' + phImg(s.best, 1280, s.cn) +
      "</div><div><h3>" + esc(s.cn) + "</h3>" +
      (s.en ? '<div class="en2">' + esc(s.en) + "</div>" : "") +
      '<div class="meta">' + metaRows + "</div>" +
      '<div class="mchart"><div class="ct">' + esc(L.months || "") +
      '</div><div class="mbars">' + bars + '</div><div class="mruler">' +
      ruler + "</div></div></div></div>" +
      '<div class="wrap" style="padding-top:26px"><div class="rel"><div ' +
      'class="ct">' + esc(L.works || "") + " (" + (s.photos || []).length +
      ')</div><div class="grid">' + rel + "</div></div></div>";
  }

  /* ---------- 启动 ---------- */
  function boot() {
    try {
      var th = new URLSearchParams(location.search).get("theme");
      if (th === "dark" || th === "light") {
        document.documentElement.setAttribute("data-theme", th);
        localStorage.setItem("bt-theme", th);
      }
    } catch (e) {}
    renderFeatured();
    renderRecent();
    renderGallery();
    renderDetail();
    var t = document.getElementById("theme");
    if (t) {
      t.addEventListener("click", function () {
        var root = document.documentElement;
        var cur = root.getAttribute("data-theme");
        if (!cur) {
          cur = window.matchMedia &&
            window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark" : "light";
        }
        var next = cur === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem("bt-theme", next); } catch (e) {}
      });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
