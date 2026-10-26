import Icon from "./Icon.jsx";
import Emoji3D from "./Emoji3D.jsx";
import { TOOL_LIST } from "../lib/tools.js";
import { resetPointer, trackPointer } from "../lib/motion.js";

/** "What would you like to do?": every tool as a colourful tile. */
export default function ToolGrid({ onOpen }) {
  return (
    <section className="tool-hub container" aria-labelledby="tool-hub-title">
      <div className="tool-hub-head">
        <span className="tool-hub-kicker">{TOOL_LIST.length} ways to shop smarter</span>
        <h2 id="tool-hub-title">What would you like to do?</h2>
      </div>
      <ul className="tool-bento">
        {TOOL_LIST.map((tool, index) => (
          <li key={tool.key} className={tool.featured ? "is-featured" : ""} style={{ "--i": index }}>
            <button
              type="button"
              className={`tool-tile tone-${tool.tone}`}
              onClick={() => onOpen(tool.key)}
              onPointerMove={trackPointer}
              onPointerLeave={resetPointer}
            >
              <span className="tool-tile-glow" aria-hidden="true" />
              <span className="tool-tile-emoji" aria-hidden="true">
                <Emoji3D name={tool.art} size={tool.featured ? 52 : 40} />
              </span>
              <span className="tool-tile-text">
                <strong>{tool.title}</strong>
                <small>{tool.text}</small>
              </span>
              <span className="tool-tile-go" aria-hidden="true">
                <Icon name="arrowRight" size={16} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
