import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

const STEPS = [
  {
    icon: "upload",
    title: "Snap, paste or describe",
    text: "Upload a product or outfit photo, paste a screenshot, or just type what you want in your own words.",
  },
  {
    icon: "sparkles",
    title: "AI understands it",
    text: "Google Lens and AI models recognise the product, every piece of an outfit, or the specs and budget you typed.",
  },
  {
    icon: "tag",
    title: "Compare, try on, buy",
    text: "See prices and stock across stores, try clothes and glasses on yourself, then buy from the seller you trust.",
  },
];

/** Fade sections in as they scroll into view. */
function useReveal() {
  useEffect(() => {
    const nodes = document.querySelectorAll(".reveal:not(.is-visible)");
    if (typeof IntersectionObserver === "undefined") {
      nodes.forEach((node) => node.classList.add("is-visible"));
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        }),
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
}

const FAQS = [
  {
    question: "How does Vistora find products?",
    answer:
      "Your photo is sent to Google Lens, which finds visually similar listings across the web. Vistora keeps the shopping results, ranks them with an AI image model by how closely they match your photo, and reads each listing's price and stock.",
  },
  {
    question: "Can I search in Hindi or by voice?",
    answer:
      "Yes. Type or speak in English, Hindi or Hinglish, like \"50k ke andar 8GB RAM wala laptop\". Tap the microphone in the text search and pick English or हिंदी. Voice search uses your browser's speech recognition.",
  },
  {
    question: "What happens to my photo?",
    answer:
      "It's sent to Google Lens only to run your search (for \"Find the outfit\", to an AI model on Groq that lists the items instead). To do that, it may sit for a few seconds at a private, unguessable temporary link, which is deleted as soon as the search starts; the Vistora server doesn't keep a copy. Your recent searches (with a small copy of each photo) and saved items stay in this browser only, and you can clear them at any time.",
  },
  {
    question: "Which stores does it search?",
    answer:
      "Any online store Google Lens finds — often Amazon, Flipkart, Myntra, AJIO, Meesho and Tata CLiQ, plus many smaller shops. Results are tuned for India.",
  },
  {
    question: "Are prices and stock always accurate?",
    answer:
      "They're read at the moment you search and can change at any time. Always confirm the price and availability on the seller's site before you buy.",
  },
  {
    question: "Can I search without a photo?",
    answer:
      "Yes. Switch the search panel to Text and type what you're looking for: keywords like \"Casio G-Shock green watch\", or a full sentence like \"an HP laptop with 8GB RAM and 512GB storage under 50k\". Vistora understands the brand, specs and budget, searches Google Shopping across Indian stores, and ranks listings by how many of your requirements they meet.",
  },
  {
    question: "Can I see how clothes look on me?",
    answer:
      "Yes. Tap \"Try on\" on any top, kurti, shirt, dress or bottom in your results, add a photo of yourself, and AI shows you wearing it in about 20–40 seconds. Use a clear, front-facing photo; a full-length one works best for long garments. Your photo is sent to free AI models on Hugging Face only to create the try-on, and is kept in your browser for next time.",
  },
  {
    question: "Can I try on sunglasses and watches?",
    answer:
      "Yes. Tap \"Try on\" on glasses, sunglasses or a watch and upload a photo of your face or wrist: Vistora places the product's real photo on your eyes or wrist, so you see the actual design. Adjust the size and position, compare before and after, and download the picture. It's made in your browser; your photo isn't uploaded.",
  },
  {
    question: "Can Vistora find a whole outfit from one photo?",
    answer:
      "Yes. Upload a photo of someone and tap \"Find the outfit\". AI identifies each item they're wearing (top, trousers, shoes, watch, glasses, bag and more) and Vistora shows shopping options for every item separately, usually in a few seconds. Clothing in the results can be tried on too.",
  },
  {
    question: "What are “Cheaper lookalikes” and deal scores?",
    answer:
      "After a photo search, Vistora shows dupes: listings that look very similar to the closest matches but cost much less, with how much you'd save. Every result also gets a deal score, like \"Great deal · 30% below typical\", comparing its price with the typical price of everything found.",
  },
  {
    question: "Why do some products say “Price on store”?",
    answer:
      "Some listings don't share their price with search engines, and some stores block automated price checks. Open the listing to see its current price.",
  },
  {
    question: "What kind of photo works best?",
    answer:
      "A clear, well-lit photo where the product fills most of the frame. Plain backgrounds help, and visible logos or labels make exact matches more likely.",
  },
];

function HowItWorks() {
  return (
    <section className="landing-section landing-band" aria-labelledby="how-title">
      <div className="container">
        <div className="section-intro section-intro-center reveal">
          <span className="eyebrow">How it works</span>
          <h2 id="how-title">From idea to best price in seconds</h2>
        </div>

        <ol className="timeline reveal">
          {STEPS.map((step, index) => (
            <li key={step.title} className="timeline-step">
              <span className="timeline-marker">
                <Icon name={step.icon} size={20} />
                <span className="timeline-number">{index + 1}</span>
              </span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// Facts about Vistora, counted up when the band scrolls into view.
const STATS = [
  { value: 11, label: "AI shopping tools", tone: "violet" },
  { value: 40, label: "listings checked per search", tone: "pink" },
  { value: 3, label: "languages: English, Hindi, Hinglish", tone: "amber" },
  { value: 0, prefix: "₹", label: "to use, no sign-up", tone: "teal" },
];
const COUNT_MS = 1200;

/** A number that counts up from 0 the first time it is on screen. */
function CountUp({ value, prefix = "" }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node || !value) return undefined;
    let frame;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      const start = performance.now();
      const tick = (now) => {
        const progress = Math.min(1, (now - start) / COUNT_MS);
        setShown(Math.round(value * (1 - Math.pow(1 - progress, 3))));
        if (progress < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [value]);

  return (
    <span ref={ref}>
      {prefix}
      {shown}
      {value >= 10 ? "+" : ""}
    </span>
  );
}

function StatsBand() {
  return (
    <section className="container stats-band" aria-label="Vistora in numbers">
      {STATS.map((stat) => (
        <div key={stat.label} className={`stat-item tone-${stat.tone}`}>
          <strong>
            <CountUp value={stat.value} prefix={stat.prefix} />
          </strong>
          <span>{stat.label}</span>
        </div>
      ))}
    </section>
  );
}

// Questions shown before "More questions".
const FAQ_SHOWN = 5;

function Faq() {
  const [showAll, setShowAll] = useState(false);
  const questions = showAll ? FAQS : FAQS.slice(0, FAQ_SHOWN);

  return (
    <section className="landing-section container faq faq-centred" aria-labelledby="faq-title">
      <div className="faq-intro reveal">
        <span className="tool-hub-kicker">Good to know</span>
        <h2 id="faq-title">Questions, answered</h2>
        <p>How Vistora finds products, what happens to your photos, and more.</p>
      </div>

      <div className="faq-list reveal">
        {questions.map((item) => (
          <details key={item.question} className="faq-item">
            <summary>
              {item.question}
              <span className="faq-toggle" aria-hidden="true" />
            </summary>
            <p>{item.answer}</p>
          </details>
        ))}
        {!showAll && FAQS.length > FAQ_SHOWN && (
          <button type="button" className="link-button faq-more" onClick={() => setShowAll(true)}>
            More questions ({FAQS.length - FAQ_SHOWN})
          </button>
        )}
      </div>
    </section>
  );
}

export default function Landing() {
  useReveal();
  return (
    <>
      <StatsBand />
      <HowItWorks />
      <Faq />
    </>
  );
}
