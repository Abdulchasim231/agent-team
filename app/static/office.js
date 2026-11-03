// Office view: every agent is a pixel Claude character at its own desk.
// Listens to /api/events and animates who is working on what.
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const W = 1000;
  const PX = 7; // size of one character pixel in scene units

  // ---------- Characters ----------
  // X body, H highlight, C cheek. Eyes and arms are separate layers so they can animate.
  const BODY = [
    "..XXXXXXXX..",
    "..XHXXXXXX..",
    "..XXXXXXXX..",
    "..XXXXXXXX..",
    "..XCXXXXCX..",
    "..XXXXXXXX..",
    "..XXXXXXXX..",
    "..X.X..X.X..",
  ];
  const EYES = { y: 2, rows: ["...E....E...", "...E....E..."] };
  const ARMS_DOWN = { y: 4, rows: ["XX........XX", "XX........XX"] };
  const ARMS_UP = { y: 3, rows: ["XX........XX", "XX........XX"] };

  const ACC = {
    crown: { y: -3, rows: ["...Y.YY.Y...", "...YYYYYY...", "...YRYYRY..."], c: { Y: "#F2C14E", R: "#D64545" } },
    tie: { y: 5, rows: [".....TT.....", "....TTTT...."], c: { T: "#33415C" } },
    headphones: {
      y: -1,
      rows: ["...KKKKKK...", "..K......K..", ".KK......KK.", ".KG......KK.", ".KK......KK."],
      c: { K: "#2E2E36", G: "#6BD49A" },
    },
    safari: { y: -3, rows: ["....HHHH....", "...BBBBBB...", ".HHHHHHHHHH."], c: { H: "#B08350", B: "#5B3E22" } },
    beret: { y: -3, rows: [".....R......", "...RRRRRR...", "..RRRRRRRRR."], c: { R: "#C8423B" } },
    glasses: {
      y: 2,
      rows: ["..G.GGGG.G..", "..G.G..G.G.."],
      c: { G: "#3B3046" },
    },
    visor: { y: -1, rows: ["..VVVVVVVV..", ".DDDDDDDDDD."], c: { V: "#3E9A6A", D: "#2F7D55" } },
  };

  const DESIGNS = {
    chief: { body: "#D97757", acc: ["crown", "tie"], screen: "inbox", prop: "phone", idle: "☕ Ready for orders" },
    coder: { body: "#7FA88E", acc: ["headphones"], screen: "code", prop: "mug", idle: "⌨️ Refactoring for fun" },
    researcher: { body: "#D4A84B", acc: ["safari"], screen: "browser", prop: "books", idle: "📚 Reading the news" },
    marketer: { body: "#D77A9C", acc: ["beret"], screen: "social", prop: "megaphone", idle: "✨ Dreaming up slogans" },
    analyst: { body: "#9585C4", acc: ["glasses"], screen: "chart", prop: "mug", idle: "📈 Admiring a spreadsheet" },
    reviewer: { body: "#5F9DB5", acc: ["visor"], screen: "doc", prop: "clipboard", idle: "🧐 Waiting for something to review" },
  };
  const SPARE_COLORS = ["#C97B63", "#6FA3A0", "#B9925E", "#8DA35F", "#A07CB0", "#6E8FC4"];
  const SPARE_ACC = [["glasses"], ["beret"], ["headphones"], ["visor"], ["safari"], []];
  const SCREENS = ["code", "doc", "browser", "chart", "social"];

  function design(name, i) {
    return DESIGNS[name] || {
      body: SPARE_COLORS[i % SPARE_COLORS.length],
      acc: SPARE_ACC[i % SPARE_ACC.length],
      screen: SCREENS[i % SCREENS.length],
      prop: "mug",
      idle: "☕ On a coffee break",
    };
  }

  function mix(a, b, t) {
    const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const [x, y] = [p(a), p(b)];
    return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
  }

  // Run-length pixel rows into crisp <rect>s.
  function pixels(rows, colors, oy = 0, px = PX) {
    let out = "";
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; ) {
        const c = row[x];
        if (!colors[c]) { x++; continue; }
        let run = 1;
        while (row[x + run] === c) run++;
        out += `<rect x="${x * px}" y="${(oy + y) * px}" width="${run * px}" height="${px}" fill="${colors[c]}"/>`;
        x += run;
      }
    });
    return out;
  }

  function characterSVG(d, px = PX) {
    const c = { X: d.body, H: mix(d.body, "#ffffff", 0.35), C: mix(d.body, "#ff8a8a", 0.45), E: "#2A2320" };
    const arms = { X: mix(d.body, "#000000", 0.08) };
    const acc = d.acc.map((k) => pixels(ACC[k].rows, ACC[k].c, ACC[k].y, px)).join("");
    return `
      <g class="bob">
        ${pixels(BODY, c, 0, px)}
        <g class="eyes">${pixels(EYES.rows, c, EYES.y, px)}</g>
        <g class="arm-b">${pixels(ARMS_DOWN.rows, arms, ARMS_DOWN.y, px)}</g>
        <g class="arm-a">${pixels(ARMS_UP.rows, arms, ARMS_UP.y, px)}</g>
        ${acc}
      </g>`;
  }

  // ---------- Desk props and screens ----------
  function screenSVG(kind) {
    const lines = (n, colors, x0 = 4) => Array.from({ length: n }, (_, i) => {
      const w = [34, 22, 40, 18, 30, 26][i % 6];
      return `<rect class="anim type" style="animation-delay:${i * 0.3}s" x="${x0 + (i % 3 === 1 ? 6 : 0)}" y="${4 + i * 5}" width="${w}" height="2.6" rx="1" fill="${colors[i % colors.length]}"/>`;
    }).join("");
    switch (kind) {
      case "code":
        return lines(5, ["#7FD1A3", "#8AB4F8", "#F5A6C8", "#F2C14E"]) +
          `<rect class="anim cursor" x="42" y="24" width="2" height="4" fill="#fff"/>`;
      case "chart":
        return [10, 18, 13, 24, 20].map((h, i) =>
          `<rect class="anim grow" style="animation-delay:${i * 0.15}s" x="${5 + i * 9}" y="${29 - h}" width="6" height="${h}" rx="1" fill="${["#8AB4F8", "#B79CF0", "#7FD1A3", "#F2C14E", "#F5A6C8"][i]}"/>`).join("");
      case "browser":
        return `<rect x="2" y="2" width="48" height="5" rx="1" fill="#3B4252"/>
          <rect x="8" y="10" width="36" height="5" rx="2.5" fill="#E6E8EE"/>
          <rect class="anim scan" x="4" y="18" width="44" height="4" rx="1" fill="rgba(138,180,248,.35)"/>` +
          lines(3, ["#8AB4F8", "#9AA3B5", "#9AA3B5"]).replace(/y="(\d+)"/g, (_, y) => `y="${+y + 15}"`);
      case "social":
        return `<rect x="6" y="4" width="40" height="24" rx="2" fill="#2B3142"/>
          <circle cx="12" cy="10" r="3" fill="#F5A6C8"/><rect x="17" y="8" width="20" height="2.5" rx="1" fill="#9AA3B5"/>
          <rect x="10" y="15" width="30" height="2.5" rx="1" fill="#E6E8EE"/>
          <path class="anim pop" d="M38 22 l3 -3 a1.8 1.8 0 0 0 -3 -2 a1.8 1.8 0 0 0 -3 2 z" fill="#FF6B8B"/>`;
      case "doc":
        return lines(4, ["#E6E8EE", "#9AA3B5"], 12) +
          [0, 1, 2, 3].map((i) => `<path class="anim tick" style="animation-delay:${i * 0.4}s" d="M4 ${6 + i * 5} l1.5 1.5 l3 -3" stroke="#6BD49A" stroke-width="1.4" fill="none"/>`).join("");
      default: // inbox
        return [0, 1, 2, 3].map((i) => `<g class="anim slide" style="animation-delay:${i * 0.25}s">
            <rect x="4" y="${3 + i * 7}" width="8" height="5" rx="1" fill="#F2C14E"/>
            <rect x="15" y="${4 + i * 7}" width="${30 - i * 4}" height="2.6" rx="1" fill="#E6E8EE"/></g>`).join("");
    }
  }

  function propSVG(kind) {
    switch (kind) {
      case "phone":
        return `<rect x="66" y="-9" width="24" height="9" rx="2" fill="#33415C"/><rect x="64" y="-15" width="28" height="6" rx="3" fill="#47577A"/>`;
      case "books":
        return `<rect x="64" y="-8" width="28" height="8" fill="#5B8DB8"/><rect x="66" y="-15" width="24" height="7" fill="#C8423B"/><rect x="65" y="-21" width="26" height="6" fill="#E3B341"/>`;
      case "megaphone":
        return `<path d="M68 -6 L84 -14 L84 2 Z" fill="#E6E8EE"/><rect x="64" y="-9" width="6" height="6" rx="1" fill="#C8423B"/><rect x="84" y="-15" width="3" height="18" rx="1" fill="#C8423B"/>`;
      case "clipboard":
        return `<rect x="66" y="-22" width="22" height="22" rx="2" fill="#B08350"/><rect x="69" y="-19" width="16" height="17" fill="#fff"/>
          <rect x="73" y="-24" width="8" height="4" rx="1" fill="#6b6f7a"/><path d="M71 -14 l2 2 l4 -4 M71 -8 l2 2 l4 -4" stroke="#3E9A6A" stroke-width="1.5" fill="none"/>`;
      default: // mug with steam
        return `<rect x="70" y="-14" width="13" height="14" rx="2" fill="#F6EFE3"/><path d="M83 -11 h3 a3 3 0 0 1 0 6 h-3" stroke="#F6EFE3" stroke-width="2" fill="none"/>
          <path class="steam" d="M74 -18 q-2 -4 0 -8 M79 -18 q2 -4 0 -8" stroke="rgba(255,255,255,.7)" stroke-width="1.5" fill="none" stroke-linecap="round"/>`;
    }
  }

  function workstationSVG(agent, d) {
    const model = (agent.resolved_model || "").split("/").pop();
    const short = model.length > 27 ? model.slice(0, 26) + "…" : model;
    return `
      <ellipse cx="0" cy="78" rx="114" ry="9" fill="rgba(70,40,20,.18)"/>
      <g class="char" transform="translate(${28 - 6 * PX} ${-7 * PX})">${characterSVG(d)}</g>
      <g class="badge done-badge" transform="translate(84 -46)"><circle r="11" fill="#3FAE6E"/><path d="M-5 0 l3.5 3.5 l6.5 -7" stroke="#fff" stroke-width="2.6" fill="none" stroke-linecap="round"/></g>
      <g class="badge err-badge" transform="translate(84 -46)"><circle r="11" fill="#E05555"/><rect x="-1.6" y="-6.5" width="3.2" height="8" rx="1.5" fill="#fff"/><circle cy="5" r="1.8" fill="#fff"/></g>
      <rect x="-86" y="-52" width="62" height="44" rx="4" fill="#2B2F3A"/>
      <rect class="screen-bg" x="-82" y="-48" width="54" height="34" rx="1.5"/>
      <g class="screen" transform="translate(-81 -47)">${screenSVG(d.screen)}</g>
      <rect x="-59" y="-8" width="8" height="6" fill="#3A3F4C"/><rect x="-68" y="-3" width="26" height="3" rx="1" fill="#3A3F4C"/>
      <g transform="translate(10 0)">${propSVG(d.prop)}</g>
      <rect x="-106" y="0" width="212" height="13" rx="2" fill="#A8754C"/>
      <rect x="-106" y="0" width="212" height="3" rx="1" fill="#C08C60"/>
      <rect x="-100" y="13" width="200" height="60" fill="#8C5E3C"/>
      <rect x="-100" y="13" width="200" height="4" fill="rgba(0,0,0,.18)"/>
      <rect x="-66" y="25" width="132" height="34" rx="6" fill="#F6EFE3" stroke="#E0D3BF"/>
      <circle class="dot" cx="-52" cy="38" r="4.5"/>
      <text x="-42" y="42.5" class="plate-name">${esc(agent.name)}</text>
      <text x="-56" y="54" class="plate-model">${esc(short)}</text>
      <title>${esc(agent.name)} · ${esc(agent.title)}</title>`;
  }

  // ---------- Room ----------
  function roomSVG(H, night) {
    const sky = night ? ["#1B2340", "#34406B"] : ["#8EC5F0", "#D8EEFB"];
    const win = (x) => `
      <g transform="translate(${x} 34)">
        <rect width="140" height="112" rx="4" fill="#F8F4EC"/>
        <rect x="7" y="7" width="126" height="98" fill="url(#sky)"/>
        ${night ? `<circle cx="100" cy="30" r="9" fill="#F4F1DE"/><circle cx="104" cy="27" r="8" fill="#34406B"/>`
                : `<circle cx="100" cy="30" r="11" fill="#FFE08A"/>`}
        <path d="M7 105 V80 h14 v-12 h12 v20 h10 V62 h16 v43 h12 V74 h14 v-16 h14 v47 h10 V84 h14 v21 Z" fill="${night ? "#141A30" : "#9DB7CC"}"/>
        ${night ? [20, 50, 66, 92, 110].map((wx, i) => `<rect x="${wx}" y="${82 + (i % 2) * 8}" width="3" height="3" fill="#F2C14E"/>`).join("") : ""}
        <rect x="67" y="7" width="6" height="98" fill="#F8F4EC"/><rect x="7" y="53" width="126" height="6" fill="#F8F4EC"/>
      </g>`;
    const spark = Array.from({ length: 8 }, (_, i) =>
      `<rect x="-2.6" y="-17" width="5.2" height="13" rx="2.6" fill="#D97757" transform="rotate(${i * 45})"/>`).join("");
    return `
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky[0]}"/><stop offset="1" stop-color="${sky[1]}"/></linearGradient>
        <pattern id="planks" width="180" height="44" patternUnits="userSpaceOnUse">
          <rect width="180" height="44" fill="#C9A17A"/>
          <rect y="21" width="180" height="2" fill="#B58D68"/><rect y="42" width="180" height="2" fill="#B58D68"/>
          <rect x="60" width="2" height="22" fill="#B58D68"/><rect x="150" y="22" width="2" height="22" fill="#B58D68"/>
          <rect x="10" y="6" width="40" height="1.5" fill="rgba(255,255,255,.08)"/>
        </pattern>
        <pattern id="wallpaper" width="28" height="28" patternUnits="userSpaceOnUse">
          <rect width="28" height="28" fill="#EFE6D8"/><rect width="14" height="28" fill="#ECE2D2"/>
        </pattern>
      </defs>
      <rect width="${W}" height="200" fill="url(#wallpaper)"/>
      <rect y="200" width="${W}" height="${H - 200}" fill="url(#planks)"/>
      <rect y="186" width="${W}" height="16" fill="#CDBBA2"/><rect y="200" width="${W}" height="6" fill="rgba(0,0,0,.08)"/>
      ${win(40)}${win(820)}
      <g transform="translate(222 38)">
        <rect width="176" height="112" rx="4" fill="#9AA0AA"/><rect x="5" y="5" width="166" height="98" rx="2" fill="#FBFBF8"/>
        <text x="16" y="28" class="wb-title">Today</text>
        <text x="16" y="52" class="wb-line" id="wb-requests">Requests: 0</text>
        <text x="16" y="72" class="wb-line" id="wb-delegations">Tasks handed out: 0</text>
        <text x="16" y="92" class="wb-line" id="wb-tools">Tool uses: 0</text>
        <rect x="120" y="106" width="30" height="4" rx="2" fill="#5B8DB8"/>
      </g>
      <g transform="translate(500 92)">
        <rect x="-82" y="-36" width="164" height="72" rx="10" fill="#2A2320"/>
        <g transform="translate(-50 0)">${spark}</g>
        <text x="-26" y="-3" class="sign-a">AGENT</text><text x="-26" y="20" class="sign-b">HEADQUARTERS</text>
      </g>
      <g transform="translate(668 92)" id="clock">
        <circle r="36" fill="#F8F4EC" stroke="#5A4634" stroke-width="5"/>
        ${Array.from({ length: 12 }, (_, i) => `<rect x="-1.5" y="-30" width="3" height="${i % 3 ? 4 : 7}" fill="#5A4634" transform="rotate(${i * 30})"/>`).join("")}
        <rect id="hand-h" x="-2.5" y="-18" width="5" height="20" rx="2.5" fill="#2A2320"/>
        <rect id="hand-m" x="-1.5" y="-27" width="3" height="29" rx="1.5" fill="#2A2320"/>
        <circle r="3.5" fill="#D97757"/>
      </g>
      <ellipse cx="500" cy="362" rx="190" ry="40" fill="#C9826A" opacity=".55"/>
      <ellipse cx="500" cy="362" rx="170" ry="32" fill="none" stroke="#F0D9C8" stroke-width="2" opacity=".6"/>
      ${plant(150, 250)}${plant(850, 250)}`;
  }

  function plant(x, y) {
    return `<g transform="translate(${x} ${y})">
      <ellipse cx="0" cy="48" rx="26" ry="6" fill="rgba(70,40,20,.18)"/>
      <path d="M0 0 C-30 -10 -34 -40 -10 -52 C-4 -30 -2 -14 0 0 Z" fill="#4E8A5B"/>
      <path d="M0 0 C30 -14 30 -44 8 -56 C4 -34 2 -16 0 0 Z" fill="#5FA06C"/>
      <path d="M0 0 C-14 -24 -4 -58 4 -66 C8 -40 6 -18 0 0 Z" fill="#6DB37A"/>
      <path d="M-20 0 h40 l-5 46 h-30 Z" fill="#D97757"/><rect x="-22" y="-2" width="44" height="8" rx="2" fill="#C2654A"/>
    </g>`;
  }

  // ---------- State ----------
  const el = (tag, attrs = {}) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const clip = (s, n) => { s = String(s ?? "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const agents = {}; // name -> { ws, bubble, card, x, y, headY, state, timer, design, history }
  const active = new Set(); // specialists currently working for the chief
  let svg, overlay, flightLayer, H;

  function layout(roster) {
    const specialists = roster.filter((a) => a.name !== "chief");
    const rows = Math.max(1, Math.ceil(specialists.length / 3));
    H = 505 + (rows - 1) * 165 + 90;
    const spots = { chief: { x: 500, y: 290, s: 1.12 } };
    specialists.forEach((a, i) => {
      const row = Math.floor(i / 3);
      const inRow = Math.min(3, specialists.length - row * 3);
      const col = i % 3;
      spots[a.name] = { x: 500 + (col - (inRow - 1) / 2) * 310, y: 505 + row * 165, s: 1 };
    });
    return spots;
  }

  function build(root, cardsRoot, roster) {
    const spots = layout(roster);
    const night = (() => { const h = new Date().getHours(); return h < 7 || h >= 19; })();
    root.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="office-svg" shape-rendering="geometricPrecision">${roomSVG(H, night)}<g id="desks"></g><g id="flights"></g></svg><div class="office-overlay"></div>`;
    svg = root.querySelector("svg");
    overlay = root.querySelector(".office-overlay");
    flightLayer = svg.querySelector("#flights");
    cardsRoot.innerHTML = "";

    // Draw back rows first so front desks overlap them.
    const ordered = [...roster].sort((a, b) => spots[a.name].y - spots[b.name].y);
    ordered.forEach((agent) => {
      const i = roster.indexOf(agent);
      const d = design(agent.name, i);
      const { x, y, s } = spots[agent.name];
      const ws = el("g", { class: "ws idle", transform: `translate(${x} ${y}) scale(${s})` });
      ws.innerHTML = workstationSVG(agent, d);
      svg.querySelector("#desks").appendChild(ws);

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      const charX = x + 28 * s;
      const headY = y - (10 * PX + 4) * s;
      bubble.style.left = `${(charX / W) * 100}%`;
      bubble.style.top = `${(headY / H) * 100}%`;
      overlay.appendChild(bubble);

      const card = document.createElement("div");
      card.className = "agent-card idle";
      card.innerHTML = `
        <svg viewBox="-6 -24 84 72" class="card-avatar" shape-rendering="crispEdges">${characterSVG(d, 6)}</svg>
        <div class="card-body">
          <div class="card-head"><b>${esc(agent.name)}</b><span class="pill">idle</span></div>
          <div class="card-title">${esc(agent.title)}</div>
          <div class="card-now">${esc(d.idle)}</div>
          <ul class="card-log"></ul>
        </div>`;
      cardsRoot.appendChild(card);
      ws.addEventListener("click", () => {
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
        card.classList.add("flash");
        setTimeout(() => card.classList.remove("flash"), 900);
      });
      agents[agent.name] = { ws, bubble, card, x: charX, y: y - 30 * s, design: d, state: "idle" };
    });
    tickClock();
    setInterval(tickClock, 30_000);
  }

  function tickClock() {
    const now = new Date();
    const m = now.getMinutes(), h = (now.getHours() % 12) + m / 60;
    svg?.querySelector("#hand-h")?.setAttribute("transform", `rotate(${h * 30})`);
    svg?.querySelector("#hand-m")?.setAttribute("transform", `rotate(${m * 6})`);
  }

  function setState(name, state, icon, text, { log = true, holdMs = 0 } = {}) {
    const a = agents[name];
    if (!a) return;
    clearTimeout(a.timer);
    a.state = state;
    a.ws.setAttribute("class", `ws ${state}`);
    a.card.className = `agent-card ${state}`;
    a.card.querySelector(".pill").textContent = state === "done" ? "done" : state;
    const shown = state === "idle" ? a.design.idle : `${icon} ${text}`;
    a.card.querySelector(".card-now").textContent = shown;
    if (state === "idle") {
      a.bubble.classList.remove("show");
    } else {
      a.bubble.className = `bubble show ${state}`;
      a.bubble.innerHTML = `<span class="b-icon">${icon}</span><span class="b-text">${esc(clip(text, 110))}</span>`;
    }
    if (log && state !== "idle") {
      const li = document.createElement("li");
      li.textContent = `${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}  ${icon} ${clip(text, 90)}`;
      const list = a.card.querySelector(".card-log");
      list.prepend(li);
      while (list.children.length > 4) list.lastChild.remove();
    }
    if (holdMs) a.timer = setTimeout(() => setState(name, "idle", "", "", { log: false }), holdMs);
  }

  function fly(from, to, kind) {
    const a = agents[from], b = agents[to];
    if (!a || !b || reduceMotion) return;
    const paper = el("g", { class: "paper" });
    paper.innerHTML = kind === "back"
      ? `<rect x="-9" y="-11" width="18" height="22" rx="2" fill="#fff" stroke="#3FAE6E" stroke-width="1.5"/><path d="M-4 0 l3 3 l5 -6" stroke="#3FAE6E" stroke-width="2" fill="none"/>`
      : `<rect x="-9" y="-11" width="18" height="22" rx="2" fill="#fff" stroke="#D9CBB5"/><rect x="-5" y="-6" width="10" height="2" fill="#B9AE9C"/><rect x="-5" y="-1" width="10" height="2" fill="#B9AE9C"/><rect x="-5" y="4" width="7" height="2" fill="#B9AE9C"/>`;
    flightLayer.appendChild(paper);
    const [x0, y0, x1, y1] = [a.x, a.y - 20, b.x, b.y - 20];
    const cx = (x0 + x1) / 2, cy = Math.min(y0, y1) - 110;
    const t0 = performance.now(), dur = 950;
    const step = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      const x = (1 - e) ** 2 * x0 + 2 * (1 - e) * e * cx + e * e * x1;
      const y = (1 - e) ** 2 * y0 + 2 * (1 - e) * e * cy + e * e * y1;
      paper.setAttribute("transform", `translate(${x} ${y}) rotate(${Math.sin(t * Math.PI * 2) * 25}) scale(${1 + Math.sin(t * Math.PI) * 0.4})`);
      if (t < 1) requestAnimationFrame(step);
      else paper.remove();
    };
    requestAnimationFrame(step);
  }

  const TOOL_VIEWS = {
    web_search: (a) => ["🔍", `Searching: ${a.query ?? ""}`],
    fetch_url: (a) => ["🌐", `Reading ${(() => { try { return new URL(a.url).host; } catch { return a.url; } })()}`],
    write_file: (a) => ["💾", `Writing ${a.path ?? "a file"}`],
    read_file: (a) => ["📖", `Reading ${a.path ?? "a file"}`],
    list_files: () => ["🗂️", "Looking through the workspace"],
  };

  function chiefWaiting() {
    if (active.size) setState("chief", "working", "⏳", `Waiting on ${[...active].join(", ")}`, { log: false });
    else setState("chief", "working", "📝", "Putting the answer together", { log: false });
  }

  function handle(e, live = true) {
    const opts = live ? {} : { log: false };
    switch (e.type) {
      case "start":
        active.clear();
        setState("chief", "working", "📨", `New request: ${e.text}`, opts);
        break;
      case "delegate":
        active.add(e.agent);
        if (live) fly("chief", e.agent, "out");
        setState("chief", "working", "🗂️", `Briefing ${e.agent}`, opts);
        setState(e.agent, "working", "📋", e.task, opts);
        if (live) setTimeout(() => agents.chief?.state === "working" && chiefWaiting(), 1200);
        break;
      case "tool": {
        if (e.agent === "chief" && String(e.tool).startsWith("delegate")) break;
        const view = TOOL_VIEWS[e.tool] || ((args) => ["🔧", `${e.tool} ${clip(JSON.stringify(args), 60)}`]);
        const [icon, text] = view(e.args || {});
        setState(e.agent, "working", icon, text, opts);
        break;
      }
      case "thought":
        setState(e.agent, "working", "💭", e.text, opts);
        break;
      case "result":
        active.delete(e.agent);
        if (live) fly(e.agent, "chief", "back");
        setState(e.agent, "done", "✅", `Done: ${e.text}`, { ...opts, holdMs: 9000 });
        if (live) chiefWaiting();
        break;
      case "error":
        active.delete(e.agent);
        setState(e.agent, "error", "⚠️", e.text, { ...opts, holdMs: 20000 });
        break;
      case "reply":
        active.clear();
        setState("chief", "done", "💬", e.text, { ...opts, holdMs: 14000 });
        break;
    }
  }

  function applySnapshot(snap) {
    const now = Date.now() / 1000;
    for (const [name, e] of Object.entries(snap.agents || {})) {
      const age = now - (e.ts || 0);
      const finished = ["result", "reply", "error"].includes(e.type);
      if (age > 600 || (finished && age > 20)) setState(name, "idle", "", "", { log: false });
      else handle(e, false);
    }
    // Specialists still busy means the chief is still waiting on them.
    active.clear();
    for (const [name, a] of Object.entries(agents)) if (name !== "chief" && a.state === "working") active.add(name);
    if (active.size) chiefWaiting();
    updateStats(snap.stats);
  }

  const stats = { requests: 0, delegations: 0, tool_calls: 0 };
  function updateStats(s) {
    if (s) Object.assign(stats, s);
    const set = (id, t) => { const n = svg?.querySelector(id); if (n) n.textContent = t; };
    set("#wb-requests", `Requests: ${stats.requests}`);
    set("#wb-delegations", `Tasks handed out: ${stats.delegations}`);
    set("#wb-tools", `Tool uses: ${stats.tool_calls}`);
  }

  function connect() {
    const source = new EventSource("/api/events");
    source.onmessage = (msg) => {
      const e = JSON.parse(msg.data);
      if (e.type === "snapshot") return applySnapshot(e);
      handle(e, true);
      const key = { start: "requests", delegate: "delegations", tool: "tool_calls" }[e.type];
      if (key) { stats[key]++; updateStats(); }
    };
  }

  window.Office = {
    init(root, cardsRoot, roster) {
      build(root, cardsRoot, roster);
      connect();
    },
  };
})();
