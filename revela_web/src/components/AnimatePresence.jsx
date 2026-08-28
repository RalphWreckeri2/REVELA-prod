import React, { useState, useEffect, useRef } from 'react';

export default function AnimatePresence({ isVisible, children, delay = 350 }) {
  const [shouldRender, setShouldRender] = useState(isVisible);
  const childrenRef = useRef(children);

  if (isVisible) {
    childrenRef.current = children;
  }

  useEffect(() => {
    let timeoutId;
    if (isVisible && !shouldRender) {
      setShouldRender(true);
    } else if (!isVisible && shouldRender) {
      timeoutId = setTimeout(() => setShouldRender(false), delay);
    }
    return () => clearTimeout(timeoutId);
  }, [isVisible, delay, shouldRender]);

  if (!shouldRender) return null;

  // Pass isClosing down to the child. When animating out (!isVisible), use the cached children
  // so components don't crash from receiving null props (e.g., when the data driving them is cleared).
  return React.cloneElement(isVisible ? children : childrenRef.current, {
    isClosing: !isVisible
  });
}
