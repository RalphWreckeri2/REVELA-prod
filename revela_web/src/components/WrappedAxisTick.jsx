import { Text } from "recharts";

const tickStyle = { fontSize: 11, fontFamily: "var(--font-base)" };

/** Wrap at word boundaries while retaining the full label for SVG tooltips. */
export default function WrappedAxisTick({ x, y, payload, width = 200, maxLines = 3, textAnchor = "end", verticalAnchor = "middle", format = value => value }) {
  return (
    <g className="wrapped-axis-tick">
      <title>{payload.value}</title>
      <Text x={x} y={y} width={width} maxLines={maxLines} textAnchor={textAnchor} verticalAnchor={verticalAnchor}
        fill="var(--color-muted)" style={tickStyle} lineHeight="1.2em">
        {format(payload.value)}
      </Text>
    </g>
  );
}
