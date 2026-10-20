import { useEffect, useRef, useState } from "react";
import { ResponsiveContainer } from "recharts";

/** Only mount Recharts after the chart area has a real, positive size.
 * Observe the area itself so sidebar toggles, tab mounts and hidden panels work
 * without a window resize or Recharts' initial (-1, -1) dimensions warning.
 * The parent must provide a definite height, or pass a number / size callback.
 */
export default function ResponsiveChart({ children, width = "100%", height = "100%", minWidth = 0, style }) {
  const ref = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    const observer = new ResizeObserver(([entry]) => {
      const next = {
        width: Math.floor(entry.contentRect.width),
        height: Math.floor(entry.contentRect.height),
      };
      setSize(current => current.width === next.width && current.height === next.height ? current : next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className="responsive-chart" style={{ width, height: typeof height === "function" ? height(size) : height, minWidth, minHeight: 0, ...style }}>
      {size.width > 0 && size.height > 0 && (
        <ResponsiveContainer width={size.width} height={size.height}>
          {typeof children === "function" ? children(size) : children}
        </ResponsiveContainer>
      )}
    </div>
  );
}
