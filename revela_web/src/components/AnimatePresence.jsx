import React, { useState, useEffect } from 'react';

export default function AnimatePresence({ isVisible, children, delay = 350 }) {
  const [renderState, setRenderState] = useState({
    isVisible,
    shouldRender: isVisible,
    children,
  });

  if (
    renderState.isVisible !== isVisible ||
    (isVisible && renderState.children !== children)
  ) {
    setRenderState((previous) => ({
      isVisible,
      shouldRender: isVisible || previous.shouldRender,
      children: isVisible ? children : previous.children,
    }));
  }

  useEffect(() => {
    if (isVisible || !renderState.shouldRender) return undefined;

    const timeoutId = setTimeout(() => {
      setRenderState((previous) => {
        if (previous.isVisible || !previous.shouldRender) return previous;
        return { ...previous, shouldRender: false };
      });
    }, delay);

    return () => clearTimeout(timeoutId);
  }, [isVisible, delay, renderState.shouldRender]);

  if (!renderState.shouldRender) return null;

  // Pass isClosing down to the child. When animating out (!isVisible), use the cached children
  // so components don't crash from receiving null props (e.g., when the data driving them is cleared).
  return React.cloneElement(isVisible ? children : renderState.children, {
    isClosing: !isVisible
  });
}
