"""Demo menu — pure data. Names and prices are made up (VND). Edit freely: the kiosk pages through whatever is here,
three items at a time.

Item: (name, short description, price, illustration key, topping colour)
Options per category: size (S/M/L price deltas), extras (toggles, price each), quantity 1–9.
"""
CATEGORIES = ("Pizza", "Burger", "Drink", "Dessert")
ACCENT = {"Pizza": "#E8573C", "Burger": "#E9952B", "Drink": "#1FA39A", "Dessert": "#D9578F", "Giỏ": "#5B5BD6"}

ITEMS = {
    "Pizza": [
        ("Margherita", "Sốt cà chua, mozzarella, húng quế", 129000, "pizza", "#4E8B3A"),
        ("Pepperoni", "Pepperoni, mozzarella, ớt chuông", 149000, "pizza", "#D9472B"),
        ("Hải sản", "Tôm, mực, sốt pesto", 169000, "pizza", "#F08A6C"),
        ("Bốn loại phô mai", "Mozzarella, cheddar, parmesan, gorgonzola", 159000, "pizza", "#F4D35E"),
        ("Gà BBQ", "Gà nướng, hành tây, sốt BBQ", 155000, "pizza", "#8C4A2F"),
        ("Rau củ", "Nấm, ớt chuông, ô liu, cà chua", 135000, "pizza", "#6BAA4A"),
        ("Hawaii", "Giăm bông, dứa, mozzarella", 145000, "pizza", "#F2B544"),
        ("Bò cay", "Bò băm, ớt jalapeño, hành", 165000, "pizza", "#B33A2B"),
        ("Xúc xích Ý", "Xúc xích, nấm, sốt kem", 152000, "pizza", "#C9744B"),
        ("Cá ngừ", "Cá ngừ, hành tây, bắp", 149000, "pizza", "#7FA7C9"),
        ("Thịt nguội", "Thịt xông khói, giăm bông, salami", 169000, "pizza", "#A84B3A"),
    ],
    "Burger": [
        ("Burger bò", "Bò nướng, xà lách, cà chua", 89000, "burger", ""),
        ("Cheeseburger", "Bò, cheddar đôi, dưa chuột", 99000, "burger", ""),
        ("Burger gà giòn", "Gà chiên giòn, sốt mayo", 85000, "burger", ""),
        ("Burger cá", "Cá phi lê, sốt tartar", 85000, "burger", ""),
        ("Burger bò đôi", "Hai lớp bò, phô mai, hành", 129000, "burger", ""),
        ("Burger chay", "Nhân đậu, rau, sốt mè", 79000, "burger", ""),
        ("Burger tôm", "Tôm chiên, bắp cải, sốt cay", 95000, "burger", ""),
        ("Burger BBQ", "Bò, hành chiên, sốt BBQ", 109000, "burger", ""),
        ("Burger nấm", "Bò, nấm xào, phô mai Thụy Sĩ", 115000, "burger", ""),
        ("Burger trứng", "Bò, trứng ốp la, thịt xông khói", 119000, "burger", ""),
    ],
    "Drink": [
        ("Trà đào", "Trà đen, đào ngâm", 45000, "drink", "#F6B26B"),
        ("Cola", "Lon 330 ml", 25000, "drink", "#6B3A22"),
        ("Trà chanh", "Trà xanh, chanh tươi", 35000, "drink", "#C9D96B"),
        ("Cà phê sữa", "Cà phê phin, sữa đặc", 39000, "drink", "#B07A4F"),
        ("Nước cam", "Cam vắt tươi", 49000, "drink", "#F59E2C"),
        ("Sinh tố bơ", "Bơ, sữa tươi", 55000, "drink", "#9CBF5E"),
        ("Trà sữa", "Trà đen, sữa, trân châu", 49000, "drink", "#D9B48F"),
        ("Soda việt quất", "Soda, siro việt quất", 42000, "drink", "#7D6BD6"),
        ("Nước suối", "Chai 500 ml", 15000, "drink", "#BFE3F2"),
        ("Matcha latte", "Matcha, sữa tươi", 55000, "drink", "#8DB86B"),
    ],
    "Dessert": [
        ("Bánh flan", "Caramen, cà phê", 32000, "dessert", "#D9578F"),
        ("Tiramisu", "Mascarpone, cacao", 59000, "dessert", "#6B3A22"),
        ("Kem vani", "Hai viên, sốt sô-cô-la", 39000, "dessert", "#F3E9DD"),
        ("Bánh sô-cô-la", "Nhân chảy", 55000, "dessert", "#5A3324"),
        ("Panna cotta", "Sốt dâu", 45000, "dessert", "#E84A5F"),
        ("Chè khúc bạch", "Hạnh nhân, vải", 35000, "dessert", "#F7F1E3"),
        ("Bánh phô mai", "New York, việt quất", 59000, "dessert", "#7D6BD6"),
        ("Bánh táo", "Táo nướng quế", 49000, "dessert", "#C9744B"),
        ("Kem dừa", "Dừa non, đậu phộng", 42000, "dessert", "#F7F1E3"),
        ("Mochi", "Ba vị: trà xanh, dâu, mè", 45000, "dessert", "#8DB86B"),
    ],
}

SIZES = {                                     # (label, description, price delta)
    "Pizza": [("S", "Nhỏ · 20 cm", -20000), ("M", "Vừa · 25 cm", 0), ("L", "Lớn · 30 cm", 40000)],
    "Drink": [("S", "Nhỏ · 350 ml", -5000), ("M", "Vừa · 500 ml", 0), ("L", "Lớn · 700 ml", 10000)],
}
EXTRAS = {                                    # (label, price)
    "Pizza": [("Nấm", 15000), ("Thêm phô mai", 20000), ("Ô liu", 15000), ("Pepperoni", 25000), ("Ớt chuông", 10000),
              ("Viền phô mai", 30000)],
    "Burger": [("Thêm phô mai", 15000), ("Thịt xông khói", 20000), ("Bỏ hành", 0), ("Thêm rau", 0), ("Trứng ốp la", 15000)],
    "Drink": [("Ít đá", 0), ("Không đá", 0), ("Ít đường", 0), ("Thêm trân châu", 10000), ("Thêm thạch", 10000)],
}
MAX_QTY = 9


def vnd(amount):
    return ("−" if amount < 0 else "") + f"{abs(amount):,.0f}đ".replace(",", ".")


def delta(amount):
    return ("+" if amount > 0 else "−" if amount < 0 else "+") + f"{abs(amount):,.0f}đ".replace(",", ".")


# ---- English (same order as above; the kiosk shows the language of the signed-in customer) ---------------------
CATEGORY_NAMES = {"vi": {"Pizza": "Pizza", "Burger": "Burger", "Drink": "Đồ uống", "Dessert": "Tráng miệng", "Giỏ": "Giỏ"},
                  "en": {"Pizza": "Pizza", "Burger": "Burgers", "Drink": "Drinks", "Dessert": "Desserts", "Giỏ": "Cart"}}
ITEMS_EN = {
    "Pizza": [
        ("Margherita", "Tomato sauce, mozzarella, basil"), ("Pepperoni", "Pepperoni, mozzarella, bell pepper"),
        ("Seafood", "Shrimp, squid, pesto"), ("Four cheese", "Mozzarella, cheddar, parmesan, gorgonzola"),
        ("BBQ chicken", "Grilled chicken, onion, BBQ sauce"), ("Veggie", "Mushroom, bell pepper, olives, tomato"),
        ("Hawaiian", "Ham, pineapple, mozzarella"), ("Spicy beef", "Minced beef, jalapeño, onion"),
        ("Italian sausage", "Sausage, mushroom, cream sauce"), ("Tuna", "Tuna, onion, sweetcorn"),
        ("Meat lovers", "Bacon, ham, salami"),
    ],
    "Burger": [
        ("Beef burger", "Grilled beef, lettuce, tomato"), ("Cheeseburger", "Beef, double cheddar, pickles"),
        ("Crispy chicken burger", "Fried chicken, mayo"), ("Fish burger", "Fish fillet, tartar sauce"),
        ("Double beef burger", "Two beef patties, cheese, onion"), ("Veggie burger", "Bean patty, greens, sesame sauce"),
        ("Shrimp burger", "Fried shrimp, cabbage, spicy sauce"), ("BBQ burger", "Beef, fried onion, BBQ sauce"),
        ("Mushroom burger", "Beef, sautéed mushroom, Swiss cheese"), ("Egg burger", "Beef, fried egg, bacon"),
    ],
    "Drink": [
        ("Peach tea", "Black tea, peach"), ("Cola", "330 ml can"), ("Lime tea", "Green tea, fresh lime"),
        ("Vietnamese milk coffee", "Drip coffee, condensed milk"), ("Orange juice", "Freshly squeezed"),
        ("Avocado smoothie", "Avocado, fresh milk"), ("Milk tea", "Black tea, milk, tapioca pearls"),
        ("Blueberry soda", "Soda, blueberry syrup"), ("Water", "500 ml bottle"), ("Matcha latte", "Matcha, fresh milk"),
    ],
    "Dessert": [
        ("Crème caramel", "Caramel, coffee"), ("Tiramisu", "Mascarpone, cocoa"), ("Vanilla ice cream", "Two scoops, chocolate sauce"),
        ("Chocolate lava cake", "Molten centre"), ("Panna cotta", "Strawberry sauce"), ("Almond jelly", "Almond, lychee"),
        ("Cheesecake", "New York style, blueberry"), ("Apple pie", "Baked apple, cinnamon"),
        ("Coconut ice cream", "Young coconut, peanuts"), ("Mochi", "Three flavours: matcha, strawberry, sesame"),
    ],
}
SIZES_EN = {"Pizza": ["Small · 20 cm", "Medium · 25 cm", "Large · 30 cm"],
            "Drink": ["Small · 350 ml", "Medium · 500 ml", "Large · 700 ml"]}
EXTRAS_EN = {"Pizza": ["Mushroom", "Extra cheese", "Olives", "Pepperoni", "Bell pepper", "Cheese crust"],
             "Burger": ["Extra cheese", "Bacon", "No onion", "Extra greens", "Fried egg"],
             "Drink": ["Less ice", "No ice", "Less sugar", "Tapioca pearls", "Jelly"]}


def category_name(cat, lang="vi"):
    return CATEGORY_NAMES.get(lang, CATEGORY_NAMES["vi"]).get(cat, cat)


def item_name(cat, i, lang="vi"):
    return ITEMS_EN[cat][i][0] if lang == "en" else ITEMS[cat][i][0]


def item_desc(cat, i, lang="vi"):
    return ITEMS_EN[cat][i][1] if lang == "en" else ITEMS[cat][i][1]


def size_desc(cat, i, lang="vi"):
    return SIZES_EN[cat][i] if lang == "en" else SIZES[cat][i][1]


def extra_label(cat, i, lang="vi"):
    return EXTRAS_EN[cat][i] if lang == "en" else EXTRAS[cat][i][0]
