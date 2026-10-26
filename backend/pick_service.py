"""
Tap any item: find every product a shopper could ask about in any photo
(a desk, a shelf, a kitchen, someone's outfit) and give each one a box, so the
page can show tappable markers. Nothing is shopped here: the visitor taps the
item they want and only that one is searched, so a busy photo costs a single
vision call and one search.
"""

from outfit_service import OutfitError, ask_vision, read_outfit

PICK_PROMPT = """You are a shopping assistant for an Indian shopping app.
Look at this photo and list every separate product a shopper might want to buy: gadgets, clothes, shoes, bags, accessories, furniture, decor, appliances, kitchenware, books, toys, anything with a price tag.

Return JSON only:
{
  "items": [
    {
      "type": short category, e.g. "headphones", "sofa", "backpack", "desk lamp",
      "description": a 3-9 word product name to search: colour, material or model if visible, then the product, e.g. "black wireless over-ear headphones",
      "box": BOX_FORMAT
    }
  ]
}
Rules:
- One entry per separate product. If several identical things sit together, list them once.
- Only things that can be bought: not people, pets, walls, floors, sky, food on a plate or the view.
- Name a brand only if it is clearly readable.
- Fit each box tightly around the product.
- At most 10 items, the biggest and most noticeable first.
- If there is nothing to buy, return {"items": []}."""


def identify_pickable(image):
    """{"items": [{"id", "type", "description", "box"}], "model"}. Raises OutfitError."""
    answer, frame, order, name = ask_vision(image, PICK_PROMPT, "Tap an item isn't set up on this server yet.")
    found = read_outfit(answer, frame, order)
    items = [
        {**item, "id": item["id"].replace("item-", "thing-")}
        for item in found["items"]
        if item.get("box")
    ]
    if not items:
        raise OutfitError("Couldn't find anything to shop in this photo. Try a clearer photo with the items in view.")
    return {"items": items, "model": name}
