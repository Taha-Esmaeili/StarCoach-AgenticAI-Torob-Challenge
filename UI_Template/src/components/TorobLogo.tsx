import React from 'react';

interface TorobLogoProps {
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | number;
  animated?: boolean;
  isThinking?: boolean;
  className?: string;
  withGlow?: boolean;
}

/**
 * Authentic 8-bit / Pixel-Art Torob Mascot Logo
 * Rendered with crisp pixel grid (16x16 pixel matrix) matching Torobchat's iconic character
 */
export const TorobLogo: React.FC<TorobLogoProps> = ({
  size = 'md',
  animated = true,
  isThinking = false,
  className = '',
  withGlow = true,
}) => {
  const getDimension = () => {
    if (typeof size === 'number') return size;
    switch (size) {
      case 'xs':
        return 22;
      case 'sm':
        return 30;
      case 'md':
        return 42;
      case 'lg':
        return 64;
      case 'xl':
        return 84;
      default:
        return 42;
    }
  };

  const dim = getDimension();

  return (
    <div
      className={`relative inline-flex items-center justify-center select-none ${className} ${
        isThinking ? 'animate-bounce' : ''
      }`}
      style={{ width: dim, height: dim }}
    >
      {/* Ambient Torob Pink Radial Glow */}
      {withGlow && (
        <div
          className={`absolute inset-0 rounded-full bg-[#e9325a]/25 blur-md -z-10 transition-opacity ${
            isThinking ? 'animate-pulse opacity-100 scale-125' : 'opacity-70'
          }`}
        />
      )}

      {/* 8-Bit Pixel Torob Mascot SVG */}
      <svg
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
        style={{
          imageRendering: 'pixelated',
          shapeRendering: 'crispEdges',
          animation: animated
            ? isThinking
              ? 'pixelWiggle 0.4s steps(2, start) infinite alternate'
              : 'pixelBob 3.5s steps(4, start) infinite alternate'
            : 'none',
        }}
      >
        {/* === PIXEL LEAVES (GREEN) === */}
        {/* Center Top Leaves */}
        <rect x="7" y="0" width="2" height="2" fill="#4ade80" />
        <rect x="7" y="2" width="2" height="2" fill="#22c55e" />
        <rect x="6" y="1" width="1" height="2" fill="#22c55e" />
        <rect x="9" y="1" width="1" height="2" fill="#16a34a" />

        {/* Left Leaf branch */}
        <rect x="4" y="1" width="2" height="1" fill="#4ade80" />
        <rect x="3" y="2" width="2" height="1" fill="#22c55e" />
        <rect x="5" y="2" width="2" height="2" fill="#16a34a" />

        {/* Right Leaf branch */}
        <rect x="10" y="1" width="2" height="1" fill="#4ade80" />
        <rect x="11" y="2" width="2" height="1" fill="#22c55e" />
        <rect x="9" y="2" width="2" height="2" fill="#15803d" />

        {/* Leaf Stems connector */}
        <rect x="7" y="3" width="2" height="1" fill="#15803d" />

        {/* === PIXEL RADISH BODY (VIBRANT RASPBERRY-PINK) === */}
        {/* Row 4 (Top of Radish) */}
        <rect x="5" y="4" width="6" height="1" fill="#ff4d79" />
        <rect x="4" y="4" width="1" height="1" fill="#e9325a" />
        <rect x="11" y="4" width="1" height="1" fill="#c21840" />

        {/* Row 5 */}
        <rect x="3" y="5" width="2" height="1" fill="#ff7597" />
        <rect x="5" y="5" width="6" height="1" fill="#ff4d79" />
        <rect x="11" y="5" width="2" height="1" fill="#c21840" />

        {/* Row 6 */}
        <rect x="2" y="6" width="2" height="1" fill="#ff7597" />
        <rect x="4" y="6" width="8" height="1" fill="#e9325a" />
        <rect x="12" y="6" width="2" height="1" fill="#9e1333" />

        {/* Row 7 (Eyes row) */}
        <rect x="2" y="7" width="2" height="1" fill="#ff7597" />
        {/* Left Eye Pixel */}
        <rect x="4" y="7" width="2" height="2" fill="#110307" />
        <rect x="4" y="7" width="1" height="1" fill="#ffffff" />
        <rect x="6" y="7" width="4" height="1" fill="#e9325a" />
        {/* Right Eye Pixel */}
        <rect x="10" y="7" width="2" height="2" fill="#110307" />
        <rect x="10" y="7" width="1" height="1" fill="#ffffff" />
        <rect x="12" y="7" width="2" height="1" fill="#9e1333" />

        {/* Row 8 */}
        <rect x="2" y="8" width="2" height="1" fill="#ff7597" />
        <rect x="6" y="8" width="4" height="1" fill="#e9325a" />
        <rect x="12" y="8" width="2" height="1" fill="#9e1333" />

        {/* Row 9 (Cheeks & Mouth) */}
        <rect x="2" y="9" width="1" height="1" fill="#ff7597" />
        <rect x="3" y="9" width="2" height="1" fill="#ff99b3" /> {/* Left Blush */}
        <rect x="5" y="9" width="2" height="1" fill="#e9325a" />
        <rect x="7" y="9" width="2" height="1" fill="#3b0512" /> {/* Cute Pixel Mouth */}
        <rect x="9" y="9" width="2" height="1" fill="#e9325a" />
        <rect x="11" y="9" width="2" height="1" fill="#ff99b3" /> {/* Right Blush */}
        <rect x="13" y="9" width="1" height="1" fill="#9e1333" />

        {/* Row 10 */}
        <rect x="3" y="10" width="2" height="1" fill="#ff4d79" />
        <rect x="5" y="10" width="6" height="1" fill="#e9325a" />
        <rect x="11" y="10" width="2" height="1" fill="#9e1333" />

        {/* Row 11 */}
        <rect x="4" y="11" width="2" height="1" fill="#ff4d79" />
        <rect x="6" y="11" width="4" height="1" fill="#c21840" />
        <rect x="10" y="11" width="2" height="1" fill="#9e1333" />

        {/* Row 12 (Tapering towards root) */}
        <rect x="5" y="12" width="2" height="1" fill="#e9325a" />
        <rect x="7" y="12" width="2" height="1" fill="#c21840" />
        <rect x="9" y="12" width="2" height="1" fill="#9e1333" />

        {/* Row 13 */}
        <rect x="6" y="13" width="4" height="1" fill="#c21840" />

        {/* Row 14 & 15 (Root Tip) */}
        <rect x="7" y="14" width="2" height="1" fill="#9e1333" />
        <rect x="7" y="15" width="1" height="1" fill="#9e1333" />
      </svg>
    </div>
  );
};
