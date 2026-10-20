"""Ordering state machine — pure Python (no Qt, no clock: ``now`` is passed in). The kiosk window draws ``view()``;
gestures and keys call the commands. Every screen shows at most three cards, matching the three head-pointing zones.

Commands (one meaning each). BCI rule: pointing and reading never trigger anything (no Midas touch); every
consequential command is a deliberate act — a nod.
    point(slot)   which card the head points at (0 = left, 1 = middle, 2 = right) — free, unlimited time
    select()      choose the pointed card (Enter / click; optional experimental dwell or double blink)
    page(step)    next / previous three cards (full head turn)
    categories()  open the category screen (look up and hold)
    yes()         nod: choose the pointed card; in a popup, confirm
    no()          shake: back / undo / cancel
    cart_open()   open the cart screen (the Cart card under Categories, or C)
    details()     double blink: the pointed item enlarged with its details — no time limit, read as long as you like;
                  nod chooses it, shake closes it (head turns are ignored while it is open)
    cart_peek()   eyes closed ~3 s: the cart over the menu — nod orders, shake closes (closes by itself too)
    login(code)   typed customer code

Texts follow ``lang`` ("vi" | "en"); cart lines keep indices, so they follow a language change too.
Orders are SIMULATED: nothing is sent anywhere.
"""
from dataclasses import dataclass, field

from . import menu
from .text import t

UNDO_S = 3.0
POPUP_S = 10.0
OVERLAY_S = 6.0
ART = {"Pizza": "pizza", "Burger": "burger", "Drink": "drink", "Dessert": "dessert"}


@dataclass
class Line:
    category: str
    index: int
    size: int                      # index in menu.SIZES[category], or -1
    extras: tuple                  # indices in menu.EXTRAS[category]
    qty: int
    unit: int

    @property
    def total(self):
        return self.unit * self.qty

    def describe(self, lang="vi"):
        name = menu.item_name(self.category, self.index, lang)
        if self.size >= 0: name += f" ({menu.SIZES[self.category][self.size][0]})"
        parts = [name]
        if self.extras: parts.append(", ".join(menu.extra_label(self.category, i, lang) for i in self.extras))
        return " · ".join(parts)


@dataclass
class Draft:
    category: str
    index: int
    size: int = 1                  # M
    extras: set = field(default_factory=set)
    qty: int = 1

    def item(self):
        return menu.ITEMS[self.category][self.index]

    def name(self, lang="vi"):
        return menu.item_name(self.category, self.index, lang)

    def unit(self):
        price = self.item()[2]
        if self.category in menu.SIZES: price += menu.SIZES[self.category][self.size][2]
        price += sum(menu.EXTRAS[self.category][i][1] for i in self.extras)
        return price

    def line(self):
        return Line(self.category, self.index, self.size if self.category in menu.SIZES else -1,
                    tuple(sorted(self.extras)), self.qty, self.unit())


class Order:
    def __init__(self, recent=(), lang="vi"):
        self.recent = list(recent)            # recent customer codes (most recent first)
        self.lang = lang
        self.guest_n = 0
        self.user = None
        self.screen = "login"
        self.focus = 1
        self.pages = {}                       # screen key → page
        self.category = menu.CATEGORIES[0]
        self.draft = None
        self.row = 0                          # cart line being edited (screen "row")
        self.cart = []
        self.popup = None                     # dict(kind, until, line)
        self.overlay = None                   # dict(kind="details" | "peek", until, card, focus) — eye shortcuts
        self.toast = None                     # dict(text, until, undo)
        self.placed = []                      # simulated orders: (user, lines, total)
        self.log = []                         # (command, screen) — what was understood, for the status line

    def tr(self, key, **kw):
        return t(key, self.lang, **kw)

    # ---- cards --------------------------------------------------------------------------------------------------
    def _key(self):
        return (self.screen, self.category if self.screen == "browse" else "")

    def page_no(self):
        return self.pages.get(self._key(), 0)

    def all_cards(self):
        s, L, tr = self.screen, self.lang, self.tr
        if s == "login":
            cards = [dict(kind="account", code=c, title=c, sub=tr("acct.recent")) for c in self.recent[:2]]
            return cards + [dict(kind="guest", title=tr("acct.guest"), sub=tr("acct.guest_sub"))]
        if s == "browse":
            cat = self.category
            return [dict(kind="item", index=i, title=menu.item_name(cat, i, L), sub=menu.item_desc(cat, i, L),
                         price=menu.vnd(it[2]), art=it[3], color=it[4]) for i, it in enumerate(menu.ITEMS[cat])]
        if s == "categories":
            n = sum(l.qty for l in self.cart)
            return ([dict(kind="category", cat=c, title=menu.category_name(c, L), sub=tr("cat.count", n=len(menu.ITEMS[c])))
                     for c in menu.CATEGORIES] +
                    [dict(kind="go_cart", title=tr("cart.card", n=n), sub=menu.vnd(self.total())),
                     dict(kind="logout", title=tr("logout"), sub=self.user or "")])
        if s == "size":
            d = self.draft
            return [dict(kind="size", index=i, title=lab, sub=menu.size_desc(d.category, i, L), price=menu.delta(dp),
                         selected=i == d.size) for i, (lab, _, dp) in enumerate(menu.SIZES[d.category])]
        if s == "extras":                      # the action card first: always reachable without paging
            d = self.draft
            done = dict(kind="extras_done", title=tr("done"), sub=tr("done.next") if d.extras else tr("done.none"))
            return [done] + [dict(kind="extra", index=i, title=menu.extra_label(d.category, i, L), price=menu.delta(p),
                                  selected=i in d.extras) for i, (_, p) in enumerate(menu.EXTRAS[d.category])]
        if s == "qty":
            d = self.draft
            return [dict(kind="minus", title="−"), dict(kind="add", title=str(d.qty), price=menu.vnd(d.unit() * d.qty)),
                    dict(kind="plus", title="+")]
        if s == "cart":
            n = sum(l.qty for l in self.cart)
            checkout = [dict(kind="checkout", title=tr("checkout"), sub=tr("checkout.sub_one") if n == 1 else tr("checkout.sub", n=n),
                             price=menu.vnd(self.total()), art="cart")] if self.cart else []
            return checkout + [dict(kind="line", index=i, title=l.describe(L), sub=f"× {l.qty}", price=menu.vnd(l.total),
                                    art=ART[l.category], color=menu.ITEMS[l.category][l.index][4]) for i, l in enumerate(self.cart)]
        if s == "row":
            l = self.cart[self.row]
            return [dict(kind="row_minus", title=tr("row.minus"), sub=l.describe(L)),
                    dict(kind="row_delete", title=tr("row.delete"), sub=tr("row.delete_sub")),
                    dict(kind="row_plus", title=tr("row.plus"), sub=tr("row.plus_sub", n=l.qty))]
        if s == "done":
            return [dict(kind="new_order", title=tr("new_order"), sub=tr("new_order.sub")),
                    dict(kind="logout", title=tr("logout"), sub=self.user or "")]
        return []

    def n_pages(self):
        return max(1, -(-len(self.all_cards()) // 3))

    def cards(self):
        p = min(self.page_no(), self.n_pages() - 1)
        return self.all_cards()[3 * p: 3 * p + 3]

    def total(self):
        return sum(l.total for l in self.cart)

    # ---- commands ---------------------------------------------------------------------------------------------------
    def _did(self, key, **kw):
        self.log.append((self.tr(key, **kw), self.screen)); self.log = self.log[-20:]
        return True

    def set_lang(self, lang):
        """Switch the texts (cards, cart lines, toasts from now on)."""
        if lang not in ("vi", "en") or lang == self.lang: return False
        self.lang = lang
        if self.overlay and self.overlay["kind"] == "details":           # the details card shows the new language
            idx = self.overlay["card"]["index"]
            self.overlay["card"] = next(c for c in self.all_cards() if c.get("index") == idx)
        return self._did("log.lang", x="English" if lang == "en" else "Tiếng Việt")

    def point(self, slot):
        if self.popup: return False
        if self.overlay and self.overlay["kind"] == "details":
            return False                       # reading the details: the head may move freely, only a shake closes
        self.focus = max(0, min(int(slot), max(0, len(self.cards()) - 1)))
        return True

    # ---- eye shortcuts (cheap if mistaken: they only show something and close by themselves) ----------------------
    def details(self, now=0.0):
        if self.popup or self.screen != "browse" or not self.cards(): return False
        if self.overlay and self.overlay["kind"] == "details":
            self.overlay = None; return self._did("log.details_close")
        card = self.cards()[min(self.focus, len(self.cards()) - 1)]
        self.overlay = dict(kind="details", until=None, card=card, focus=self.focus)
        return self._did("log.details")

    def item_details(self, card):
        """Lines for the details overlay of a browse card: description, sizes with prices, extras."""
        cat, L = self.category, self.lang
        it = menu.ITEMS[cat][card["index"]]
        lines = [menu.item_desc(cat, card["index"], L)]
        if cat in menu.SIZES:
            lines.append(self.tr("details.size") + ": " + " · ".join(f"{lab} {menu.vnd(it[2] + d)}" for lab, _, d in menu.SIZES[cat]))
        if cat in menu.EXTRAS:
            lines.append(self.tr("details.extras") + ": " + ", ".join(menu.extra_label(cat, i, L) for i in range(len(menu.EXTRAS[cat]))))
        return lines

    def cart_peek(self, now=0.0):
        if self.popup or self.screen in ("login", "done"): return False
        if self.overlay and self.overlay["kind"] == "peek":
            self.overlay = None; return self._did("log.peek_close")
        self.overlay = dict(kind="peek", until=now + OVERLAY_S)
        return self._did("log.peek")

    def page(self, step):
        if self.popup or self.n_pages() <= 1: return False
        if self.overlay and self.overlay["kind"] == "details": return False
        self.pages[self._key()] = (self.page_no() + step) % self.n_pages()
        self.focus = min(self.focus, len(self.cards()) - 1)
        self.log.append((self.tr("log.page") + (" ›" if step > 0 else " ‹"), self.screen))
        return True

    def _go(self, screen, focus=1):
        self.screen = screen
        self.focus = min(focus, max(0, len(self.cards()) - 1))

    def login(self, code, now=0.0):
        code = (code or "").strip()
        if not code or self.screen != "login": return False
        self.user = code
        if code in self.recent: self.recent.remove(code)
        self.recent.insert(0, code)
        self.cart, self.draft = [], None
        self.category = menu.CATEGORIES[0]; self.pages = {}
        self._go("browse")
        self._toast(self.tr("toast.hello", code=code), now)
        return self._did("log.login")

    def select(self, now=0.0):
        if self.popup: return False
        self.overlay = None
        cards = self.cards()
        if not cards: return False
        c = cards[min(self.focus, len(cards) - 1)]
        k = c["kind"]
        if k == "account": return self.login(c["code"], now)
        if k == "guest":
            self.guest_n += 1
            return self.login(self.tr("guest_code", n=self.guest_n), now)
        if k == "item":
            self.draft = Draft(self.category, c["index"])
            self._go(self._first_option())
            return self._did("log.choose", x=c["title"])
        if k == "category":
            self.category = c["cat"]; self._go("browse")
            return self._did("log.category", x=c["title"])
        if k == "go_cart": return self.cart_open()
        if k == "logout":
            if self.cart and self.screen != "done":
                self.popup = dict(kind="logout", until=now + POPUP_S); return self._did("log.logout?")
            return self._logout()
        if k == "size":
            self.draft.size = c["index"]; self._go(self._after("size"))
            return self._did("log.size", x=c["title"])
        if k == "extras_done":
            self._go(self._after("extras")); return self._did("log.extras_done")
        if k == "checkout":
            self.popup = dict(kind="order", until=now + POPUP_S); return self._did("log.order?")
        if k == "extra":
            self.draft.extras ^= {c["index"]}
            return self._did("log.on" if c["index"] in self.draft.extras else "log.off", x=c["title"])
        if k == "minus":
            self.draft.qty = max(1, self.draft.qty - 1); return self._did("log.minus")
        if k == "plus":
            self.draft.qty = min(menu.MAX_QTY, self.draft.qty + 1); return self._did("log.plus")
        if k == "add":
            line = self.draft.line()
            self.cart.append(line); self.draft = None
            self._go("browse")
            self._toast(self.tr("toast.added", item=line.describe(self.lang), n=line.qty), now, undo=True)
            return self._did("log.added")
        if k == "line":
            self.row = c["index"]; self._go("row")
            return self._did("log.line", x=c["index"] + 1)
        if k == "row_minus":
            l = self.cart[self.row]
            if l.qty > 1: l.qty -= 1; return self._did("log.minus")
            self.popup = dict(kind="delete", until=now + POPUP_S, line=self.row); return self._did("log.delete?")
        if k == "row_delete":
            self.popup = dict(kind="delete", until=now + POPUP_S, line=self.row); return self._did("log.delete?")
        if k == "row_plus":
            self.cart[self.row].qty = min(menu.MAX_QTY, self.cart[self.row].qty + 1); return self._did("log.plus")
        if k == "new_order":
            self.cart = []; self.category = menu.CATEGORIES[0]; self.pages = {}; self._go("browse")
            return self._did("log.new_order")
        return False

    def yes(self, now=0.0):
        if self.overlay and not self.popup:
            ov, self.overlay = self.overlay, None
            if ov["kind"] == "peek":
                if not self.cart: return self._did("log.empty")
                self.popup = dict(kind="order", until=now + POPUP_S); return self._did("log.order?")
            self.focus = ov["focus"]                                    # details: nod chooses that item
            return self.select(now)
        if self.popup:
            p, self.popup = self.popup, None
            if p["kind"] == "order":
                self.placed.append((self.user, list(self.cart), self.total()))
                self._go("done"); self._toast(self.tr("toast.ordered"), now)
            elif p["kind"] == "delete":
                removed = self.cart.pop(p["line"])
                self._go("cart" if self.cart else "browse")
                self._toast(self.tr("toast.removed", item=removed.describe(self.lang)), now)
            elif p["kind"] == "logout":
                self._logout()
            return self._did("log.yes")
        return self.select(now)                 # a nod chooses the pointed card

    def no(self, now=0.0):
        if self.popup:
            self.popup = None; return self._did("log.cancel")
        if self.overlay:
            self.overlay = None; return self._did("log.close")
        if self.toast and self.toast.get("undo") and now <= self.toast["undo_until"] and self.cart:
            line = self.cart.pop(); self.toast = None
            self._toast(self.tr("toast.undone", item=line.describe(self.lang)), now)
            return self._did("log.undo")
        back = {"browse": "categories", "categories": "browse", "size": "browse", "cart": "browse", "row": "cart",
                "done": None}
        s = self.screen
        if s == "extras": self._go(self._before("extras")); return self._did("log.back")
        if s == "qty": self._go(self._before("qty")); return self._did("log.back")
        if s in back and back[s]:
            if s == "size": self.draft = None
            self._go(back[s]); return self._did("log.back")
        if s == "done": return self._logout()
        return False

    def categories(self):
        if self.popup or self.screen in ("login", "done"): return False
        self.draft = None if self.screen in ("size", "extras", "qty") else self.draft
        self.overlay = None
        self._go("categories"); return self._did("log.categories")

    def open_category(self, cat):
        """A category tab in the top bar (mouse)."""
        if self.popup or self.overlay or self.screen in ("login", "done") or cat not in menu.CATEGORIES: return False
        self.draft = None; self.category = cat; self._go("browse")
        return self._did("log.category", x=menu.category_name(cat, self.lang))

    def cart_open(self):
        if self.popup or self.screen in ("login", "done"): return False
        self.draft = None; self.overlay = None
        self._go("cart", focus=0); return self._did("log.cart")

    def tick(self, now):
        """Expire the popup (cancel) and the toast."""
        if self.popup and now > self.popup["until"]:
            self.popup = None; self._did("log.timeout")
        if self.toast and now > self.toast["until"]: self.toast = None
        if self.overlay and not self.popup and self.overlay["until"] is not None and now > self.overlay["until"]:
            self.overlay = None                # only the cart peek (often a false eye closure) closes by itself

    # ---- helpers ------------------------------------------------------------------------------------------------
    def _steps(self):
        c = self.draft.category
        return [s for s, ok in (("size", c in menu.SIZES), ("extras", c in menu.EXTRAS), ("qty", True)) if ok]

    def _first_option(self):
        return self._steps()[0]

    def _after(self, step):
        st = self._steps(); return st[st.index(step) + 1]

    def _before(self, step):
        st = self._steps(); i = st.index(step)
        if i == 0: self.draft = None; return "browse"
        return st[i - 1]

    def _toast(self, text, now, undo=False):
        """The message stays 2 s longer than the undo window, so it can still be read after undo has ended."""
        self.toast = dict(text=text, until=now + (UNDO_S + 2.0 if undo else 2.5), undo=undo,
                          undo_until=now + UNDO_S if undo else None)

    def _logout(self):
        self.user, self.cart, self.draft, self.popup = None, [], None, None
        self._go("login"); return self._did("log.signed_out")
