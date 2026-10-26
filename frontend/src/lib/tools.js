// Everything Vistora can do. Photo tools share one page (the photo is used
// for the chosen purpose). Each tool has its own colour (tone) and a 3D emoji
// picture (art, in /emoji) for its tile; `featured` tools get the big tiles on the home page.
export const TOOL_LIST = [
  { key: "photo", icon: "camera", art: "camera", tone: "violet", featured: true, title: "Search by photo", text: "Snap or upload a product; see every store and the cheapest price." },
  { key: "outfit", icon: "shirt", art: "dress", tone: "pink", featured: true, title: "Find the outfit", text: "Shop every item someone is wearing in a photo." },
  { key: "plan", icon: "tag", art: "target", tone: "amber", featured: true, title: "Plan a look on a budget", text: "A complete outfit for any occasion that fits your budget." },
  { key: "gift", icon: "heart", art: "gift", tone: "rose", featured: true, title: "Find a gift", text: "Six thoughtful gift ideas for anyone, at any budget." },
  { key: "pick", icon: "scan", art: "sparkles", tone: "teal", title: "Tap any item", text: "Snap a desk, shelf or scene, then tap the one thing you want to buy." },
  { key: "rate", icon: "star", art: "star", tone: "orange", title: "Rate my outfit", text: "A style score out of 10, with tips you can shop." },
  { key: "colours", icon: "palette", art: "palette", tone: "teal", title: "Colours that suit me", text: "One selfie tells us the colours that flatter you." },
  { key: "tryon", icon: "sparkles", art: "sunglasses", tone: "indigo", title: "Try it on", text: "See clothes, glasses or a watch on your own photo." },
  { key: "list", icon: "bag", art: "memo", tone: "green", title: "Shop my list", text: "Photograph or type a shopping list; get every item in one cart." },
  { key: "room", icon: "box", art: "couch", tone: "cyan", title: "Shop a room", text: "Find the furniture and decor from any room photo." },
  { key: "watch", icon: "bell", art: "bell", tone: "blue", title: "Price watch", text: "Tap the bell on any product; we'll tell you when it gets cheaper." },
];

export const TOOLS = Object.fromEntries(TOOL_LIST.map((tool) => [tool.key, tool]));
