(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  const initData = (tg && tg.initData) || "";
  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("#100e0c");
    if (tg.setBackgroundColor) tg.setBackgroundColor("#100e0c");
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    if (tg.BackButton) tg.BackButton.onClick(() => back());
  }

  const view = document.getElementById("view");
  const backBtn = document.getElementById("back");
  const banner = document.getElementById("banner");
  const toast = document.getElementById("toast");
  const stack = [];
  const draft = {};
  let catalog = null;
  let session = null;
  let drawToken = 0;

  banner.hidden = Boolean(initData);
  banner.textContent = initData
    ? ""
    : "Просмотр на компьютере. Заявка администратору не уйдёт.";

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function button(label, cls, action) {
    const node = el("button", cls, label);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }

  function showToast(text) {
    toast.hidden = !text;
    toast.textContent = text || "";
  }

  function syncBack() {
    const nested = stack.length > 1;
    backBtn.hidden = !nested;
    if (tg && tg.BackButton) {
      if (nested) tg.BackButton.show();
      else tg.BackButton.hide();
    }
  }

  function go(name, params) {
    stack.push({ name, params: params || {} });
    render();
  }

  function back() {
    if (stack.length > 1) stack.pop();
    render();
  }

  backBtn.addEventListener("click", back);

  async function api(path, body) {
    const response = await fetch(path, body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, initData }),
        }
      : undefined);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || "Не получилось. Попробуйте ещё раз.");
    }
    return data;
  }

  function offerOf(hall, id) {
    return (catalog.offers[hall] || []).find((item) => item.id === id);
  }

  function resetDraft() {
    Object.keys(draft).forEach((key) => delete draft[key]);
  }

  function blocks(list, skip) {
    const wrap = el("div");
    (list || []).forEach((block) => {
      const lines = block.lines || [];
      if (block.heading === skip && !lines.length) return;
      const box = el("section", "block");
      if (block.heading && block.heading !== skip) box.append(el("h3", null, block.heading));
      lines.forEach((line) => box.append(el("p", null, line)));
      if (box.childNodes.length) wrap.append(box);
    });
    return wrap;
  }

  function screenHome() {
    const near = catalog.nearest;
    view.append(el("h1", null, "Четыре часа"));
    catalog.welcome.slice(1).forEach((line) => view.append(el("p", "lead", line)));

    const card = el("section", "card");
    card.append(el("p", "kicker", near.when));
    card.append(el("p", "window", near.window));
    card.append(el("p", "price", near.price_label));
    catalog.brief.forEach((line) => card.append(el("p", "quiet", line)));
    const pair = el("div", "pair");
    pair.append(button("Женский", "go", () => takeNearest("female")));
    pair.append(button("Мужской", "go", () => takeNearest("male")));
    card.append(pair);
    view.append(card);

    const navs = el("div", "navs");
    navs.append(button("Женский разряд", "nav", () => openHall("female")));
    navs.append(button("Мужской разряд", "nav", () => openHall("male")));
    navs.append(button("Мой жар", "nav", () => go("heat")));
    navs.append(button("Ещё", "nav", () => go("more")));
    view.append(navs);
  }

  function takeNearest(hall) {
    const near = catalog.nearest;
    resetDraft();
    Object.assign(draft, {
      kind: "visit",
      hall,
      offer: "ticket",
      date: near.date,
      start: near.start,
      extra: "none",
    });
    go("guests");
  }

  async function openHall(hall) {
    try {
      const data = await api("/api/touch", { what: hall });
      showToast((data.notes || []).join(" · "));
    } catch (error) {
      showToast("");
    }
    go("hall", { hall });
  }

  function screenHall(params) {
    const hall = catalog.halls[params.hall];
    view.append(el("h2", null, hall.title));
    view.append(blocks(hall.blocks, hall.title));
    if (hall.bookable) {
      view.append(button("Забронировать этот разряд", "go", () => {
        resetDraft();
        draft.kind = "visit";
        draft.hall = params.hall;
        go("offer");
      }));
    }
    const other = params.hall === "female" ? "male" : "female";
    view.append(button(catalog.halls[other].title, "nav", () => openHall(other)));
    view.append(button("Скоро откроется", "nav", () => go("spaces")));
  }

  function screenOffer() {
    view.append(el("h2", null, catalog.halls[draft.hall].title));
    view.append(el("p", "lead", "Что бронируем?"));
    const stackBox = el("div", "stack");
    catalog.offers[draft.hall].forEach((offer) => {
      stackBox.append(button(offer.title, "nav", () => {
        draft.offer = offer.id;
        draft.extra = "none";
        go("day");
      }));
    });
    view.append(stackBox);
  }

  async function screenDay(_params, token) {
    view.append(el("h2", null, "День"));
    const offer = offerOf(draft.hall, draft.offer);
    view.append(el("p", "lead", offer ? offer.title : ""));
    const row = el("div", "days");
    view.append(row);
    const data = await api(`/api/days?hall=${encodeURIComponent(draft.hall)}&offer=${encodeURIComponent(draft.offer)}`);
    if (token !== drawToken) return;
    data.days.forEach((day) => {
      row.append(button(day.label, draft.date === day.date ? "chip on" : "chip", () => {
        draft.date = day.date;
        draft.start = "";
        go("slot");
      }));
    });
  }

  async function screenSlot(_params, token) {
    view.append(el("h2", null, "Окно входа"));
    const row = el("div", "stack");
    view.append(row);
    const data = await api(
      `/api/slots?hall=${encodeURIComponent(draft.hall)}&offer=${encodeURIComponent(draft.offer)}&date=${encodeURIComponent(draft.date)}`
    );
    if (token !== drawToken) return;
    data.slots.forEach((slot) => {
      row.append(button(`${slot.label} · ${slot.price_label}`, "nav", () => {
        draft.start = slot.start;
        go("guests");
      }));
    });
  }

  function screenGuests() {
    const offer = offerOf(draft.hall, draft.offer);
    const cap = offer ? offer.cap : 8;
    view.append(el("h2", null, "Сколько гостей?"));
    view.append(el("p", "lead", catalog.halls[draft.hall].title));
    const grid = el("div", "nums");
    for (let number = 1; number <= cap; number += 1) {
      grid.append(button(String(number), draft.guests === number ? "num on" : "num", () => {
        draft.guests = number;
        go("extra");
      }));
    }
    view.append(grid);
  }

  function screenExtra() {
    view.append(el("h2", null, "К визиту"));
    view.append(el("p", "lead", "Можно пропустить. Цены из меню комплекса."));
    const box = el("div", "stack");
    catalog.upsells.forEach((item) => {
      box.append(button(item.title, "nav", () => {
        draft.extra = item.id;
        go("who");
      }));
    });
    view.append(box);
  }

  function screenWho() {
    const gift = draft.kind === "certificate";
    view.append(el("h2", null, gift ? "Кому подарок" : "Как к вам обращаться"));
    const name = el("input");
    name.autocomplete = "name";
    name.maxLength = 40;
    name.value = draft.name || "";
    name.placeholder = gift ? "Имя получателя" : "Имя";
    const phone = el("input");
    phone.autocomplete = "tel";
    phone.inputMode = "tel";
    phone.value = draft.phone || "";
    phone.placeholder = "8 925 000-00-00";
    view.append(el("label", null, "Имя"));
    name.id = "guest-name";
    view.lastChild.htmlFor = "guest-name";
    view.append(name);
    view.append(el("label", null, "Телефон"));
    phone.id = "guest-phone";
    view.lastChild.htmlFor = "guest-phone";
    view.append(phone);
    const error = el("p", "error");
    error.hidden = true;
    view.append(error);
    view.append(button("Дальше", "go", async () => {
      draft.name = name.value.trim();
      draft.phone = phone.value.trim();
      error.hidden = true;
      try {
        draft.quote = await api("/api/quote", draft);
        go("confirm");
      } catch (err) {
        error.hidden = false;
        error.textContent = err.message;
      }
    }));
  }

  function screenConfirm() {
    const quoted = draft.quote || { lines: [], estimate: "", note: "", consent: "" };
    view.append(el("h2", null, "Заявка"));
    const sum = el("div", "sum");
    quoted.lines.forEach((line) => sum.append(el("p", null, line)));
    view.append(sum);
    view.append(el("p", "lead", quoted.estimate));
    if (quoted.note) view.append(el("p", "quiet", quoted.note));
    view.append(el("p", "quiet", "Место появляется после подтверждения администратора."));
    view.append(el("p", "quiet", quoted.consent));
    const error = el("p", "error");
    error.hidden = true;
    view.append(error);
    view.append(button("Отправить заявку", "go", async () => {
      error.hidden = true;
      try {
        const data = await api("/api/booking", draft);
        draft.done = data;
        if (!data.preview) session = await api("/api/session", {});
        go("done");
      } catch (err) {
        error.hidden = false;
        error.textContent = err.message;
      }
    }));
  }

  function screenDone() {
    const data = draft.done || {};
    view.append(el("h2", null, data.preview ? "Просмотр" : "Заявка ушла"));
    view.append(el("p", "lead", data.message || ""));
    if (data.coals) view.append(el("p", "quiet", data.coals));
    (data.arrival || []).forEach((line) => view.append(el("p", "quiet", line)));
    view.append(button("На главную", "ghost", () => {
      resetDraft();
      stack.splice(0, stack.length);
      go("home");
    }));
  }

  function screenMore() {
    view.append(el("h2", null, "Ещё"));
    const box = el("div", "navs");
    box.append(button("Тариф", "nav", () => openInfo("tariffs")));
    box.append(button("Пар по часам", "nav", () => openInfo("schedule")));
    box.append(button("Парения и SPA", "nav", () => go("spa")));
    box.append(button("Для кого визит", "nav", () => go("fit")));
    box.append(button("Подарок", "nav", () => go("gift")));
    box.append(button("Коротко до заявки", "nav", () => go("faq")));
    box.append(button("Контакты", "nav", () => go("contacts")));
    box.append(button("Первый визит", "nav", () => go("visit")));
    box.append(button("Ресторан", "nav", () => go("restaurant")));
    box.append(button("Скоро откроется", "nav", () => go("spaces")));
    view.append(box);
  }

  async function openInfo(what) {
    try {
      const data = await api("/api/touch", { what });
      showToast((data.notes || []).join(" · "));
    } catch (error) {
      showToast("");
    }
    go(what);
  }

  function screenTariffs() {
    view.append(el("h2", null, "Билеты"));
    view.append(blocks(catalog.tariffs, "Билеты"));
    view.append(button("Занять ближайшее", "go", () => {
      stack.splice(0, stack.length, { name: "home", params: {} });
      render();
    }));
  }

  function screenSchedule() {
    view.append(el("h2", null, "Авторский пар"));
    view.append(el("p", "lead", "Каждые 1,5 часа, в мужском и женском разрядах одинаково. Входит в билет."));
    catalog.steam.forEach((time) => view.append(el("p", null, time)));
    view.append(el("p", "quiet", "Сеанс билета — 4 часа с момента входа."));
    const pair = el("div", "pair");
    pair.append(button("Женский", "ghost", () => openHall("female")));
    pair.append(button("Мужской", "ghost", () => openHall("male")));
    view.append(pair);
  }

  function screenSpa() {
    view.append(el("h2", null, "Парения и SPA"));
    view.append(blocks(catalog.spa, "Парения и SPA"));
  }

  function screenFit() {
    view.append(el("h2", null, "Для кого визит"));
    const box = el("div", "navs");
    catalog.fit.forEach((item) => {
      box.append(button(item.title, "nav", () => go("fit-one", { id: item.id })));
    });
    view.append(box);
  }

  function screenFitOne(params) {
    const item = catalog.fit.find((row) => row.id === params.id);
    view.append(el("h2", null, item.title));
    view.append(el("p", "lead", item.text));
    if (item.id === "gift") {
      view.append(button("Выбрать сумму", "go", () => go("gift")));
      return;
    }
    if (item.id === "company") {
      view.append(button("Мужской VIP и кабина", "go", () => {
        resetDraft();
        draft.kind = "visit";
        draft.hall = "male";
        go("offer");
      }));
      return;
    }
    const pair = el("div", "pair");
    pair.append(button("Женский", "go", () => takeNearest("female")));
    pair.append(button("Мужской", "go", () => takeNearest("male")));
    view.append(pair);
  }

  function screenGift() {
    view.append(el("h2", null, "Сертификат"));
    view.append(el("p", "lead", "На сумму из прайса. Администратор подготовит."));
    const box = el("div", "navs");
    catalog.certificates.forEach((item) => {
      box.append(button(item.title, "nav", () => {
        resetDraft();
        draft.kind = "certificate";
        draft.amount = item.amount;
        go("who");
      }));
    });
    view.append(box);
  }

  function screenFaq() {
    view.append(el("h2", null, "Коротко"));
    const box = el("div", "navs");
    catalog.faq.forEach((item) => {
      box.append(button(item.title, "nav", () => go("faq-one", { id: item.id })));
    });
    view.append(box);
  }

  function screenFaqOne(params) {
    const item = catalog.faq.find((row) => row.id === params.id);
    view.append(el("h2", null, item.title));
    view.append(el("p", "lead", item.text));
    const pair = el("div", "pair");
    pair.append(button("Женский", "go", () => takeNearest("female")));
    pair.append(button("Мужской", "go", () => takeNearest("male")));
    view.append(pair);
  }

  function safeHref(url) {
    if (typeof url !== "string") return "";
    if (url.startsWith("https://") || url.startsWith("tel:")) return url;
    return "";
  }

  function screenContacts() {
    view.append(el("h2", null, "Контакты"));
    view.append(el("p", null, catalog.brand));
    view.append(el("p", null, catalog.address));
    view.append(el("p", "quiet", catalog.hours));
    const phone = safeHref(`tel:${catalog.phone_tel}`);
    if (phone) {
      const link = el("a", "nav", catalog.phone_display);
      link.href = phone;
      view.append(link);
    }
    const box = el("div", "navs");
    const links = [
      ["Маршрут", catalog.links.map],
      ["Сайт", catalog.links.site],
      ["Telegram", catalog.links.telegram],
      ["Instagram", catalog.links.instagram],
      ["ВКонтакте", catalog.links.vk],
      ["WhatsApp", catalog.links.whatsapp],
    ];
    links.forEach(([label, href]) => {
      const safe = safeHref(href);
      if (!safe) return;
      const link = el("a", "nav", label);
      link.href = safe;
      link.target = "_blank";
      link.rel = "noopener";
      box.append(link);
    });
    view.append(box);
  }

  function screenVisit() {
    view.append(el("h2", null, "Первый визит"));
    view.append(blocks(catalog.first_visit, "Первый визит"));
  }

  function screenRestaurant() {
    view.append(el("h2", null, "Ресторан"));
    view.append(blocks(catalog.restaurant, "Ресторан"));
  }

  function screenSpaces() {
    view.append(el("h2", null, "Скоро откроется"));
    view.append(el("p", "lead", "Нажмите зал — оставим вас в листе, когда он заработает."));
    const box = el("div", "stack");
    catalog.coming_soon.forEach((item) => {
      const block = el("div");
      block.append(el("p", null, item.text));
      block.append(button("В лист", "ghost", async () => {
        try {
          const data = await api("/api/wait", { space: item.id });
          showToast(data.message);
        } catch (error) {
          showToast(error.message);
        }
      }));
      box.append(block);
    });
    view.append(box);
    view.append(button("Ресторан", "nav", () => go("restaurant")));
  }

  function lights(on, total) {
    return "●".repeat(on) + "○".repeat(Math.max(total - on, 0));
  }

  function screenHeat() {
    const me = session || {};
    view.append(el("h2", null, "Мой жар"));
    view.append(el("p", "lights", lights(me.lights || 1, me.lights_total || 5)));
    view.append(el("p", "price", me.rank || "Искра"));
    view.append(el("p", "lead", me.about || ""));
    if (me.next) view.append(el("p", "quiet", `Дальше — ${me.next}. Зажигается подтверждённым визитом.`));
    else view.append(el("p", "quiet", "Все пять огоньков. На входе встречают по имени."));
    view.append(el("p", "quiet", `Визитов: ${me.visits || 0}`));
    if ((me.achievements || []).length) {
      view.append(el("p", "quiet", me.achievements.join(" · ")));
    }
    view.append(button("Огонёк на сегодня", "go", async () => {
      try {
        const data = await api("/api/ritual", {});
        go("ritual", data);
      } catch (error) {
        showToast(error.message);
      }
    }));
    (me.bookings || []).forEach((item) => {
      const card = el("section", "card");
      card.append(el("p", "kicker", `№${item.id} · ${item.status_label}`));
      card.append(el("p", null, item.hall));
      card.append(el("p", "quiet", `${item.date}, ${item.slot}`));
      card.append(el("p", "quiet", `Гостей: ${item.guests}`));
      if (item.can_cancel) {
        card.append(button("Отменить заявку", "ghost", async () => {
          try {
            const data = await api("/api/cancel", { id: item.id });
            showToast(data.message);
            session = await api("/api/session", {});
            render();
          } catch (error) {
            showToast(error.message);
          }
        }));
      }
      view.append(card);
    });
  }

  function screenRitual(params) {
    view.append(el("h2", null, "Ритуал дня"));
    view.append(el("p", "lead", params.text || ""));
    if (params.taken) view.append(el("p", "quiet", "На сегодня уже забран."));
    (params.notes || []).forEach((note) => view.append(el("p", "quiet", note)));
    if (params.preview) view.append(el("p", "quiet", "Угольки за ритуал засчитаются в Telegram."));
  }

  const screens = {
    home: screenHome,
    hall: screenHall,
    offer: screenOffer,
    day: screenDay,
    slot: screenSlot,
    guests: screenGuests,
    extra: screenExtra,
    who: screenWho,
    confirm: screenConfirm,
    done: screenDone,
    more: screenMore,
    tariffs: screenTariffs,
    schedule: screenSchedule,
    spa: screenSpa,
    fit: screenFit,
    "fit-one": screenFitOne,
    gift: screenGift,
    faq: screenFaq,
    "faq-one": screenFaqOne,
    contacts: screenContacts,
    visit: screenVisit,
    restaurant: screenRestaurant,
    spaces: screenSpaces,
    heat: screenHeat,
    ritual: screenRitual,
  };

  function render() {
    const token = ++drawToken;
    const frame = stack[stack.length - 1];
    clear(view);
    syncBack();
    const draw = screens[frame.name];
    if (!draw) return;
    Promise.resolve(draw(frame.params, token)).catch((error) => {
      if (token !== drawToken) return;
      view.append(el("p", "error", error.message));
    });
  }

  async function boot() {
    view.append(el("p", "lead", "Открываем залы…"));
    try {
      catalog = await api("/api/catalog");
      session = await api("/api/session", {});
      stack.push({ name: "home", params: {} });
      render();
    } catch (error) {
      clear(view);
      view.append(el("p", "error", error.message));
    }
  }

  boot();
})();
