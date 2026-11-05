import React from 'react';

/**
 * Animated searching token showing Torob flipping and searching through
 * catalog papers, shop lists, and invoices with a cute magnifying glass and shimmer.
 */
export const SearchingPapersAnimation: React.FC<{ size?: number }> = ({ size = 38 }) => {
  return (
    <div
      className="relative flex items-center justify-center select-none"
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
      >
        <defs>
          <linearGradient id="paperGrad1" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#2a2a36" />
            <stop offset="100%" stopColor="#1a1a24" />
          </linearGradient>
          <linearGradient id="paperGrad2" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#353545" />
            <stop offset="100%" stopColor="#222230" />
          </linearGradient>
          <linearGradient id="paperGrad3" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ff4d79" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#e9325a" stopOpacity="0.05" />
          </linearGradient>
          <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* --- Back Catalog Paper (Tilting Left) --- */}
        <g className="paper-page-back">
          <rect
            x="8"
            y="12"
            width="22"
            height="28"
            rx="3"
            fill="url(#paperGrad1)"
            stroke="#3a3a4c"
            strokeWidth="1.2"
          />
          {/* Mock catalog lines */}
          <line x1="12" y1="18" x2="24" y2="18" stroke="#4a4a60" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="12" y1="23" x2="22" y2="23" stroke="#4a4a60" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="12" y1="28" x2="26" y2="28" stroke="#4a4a60" strokeWidth="1.5" strokeLinecap="round" />
        </g>

        {/* --- Middle Catalog Paper (Shifting & Searching) --- */}
        <g className="paper-page-mid">
          <rect
            x="14"
            y="9"
            width="22"
            height="28"
            rx="3"
            fill="url(#paperGrad2)"
            stroke="#4e4e66"
            strokeWidth="1.2"
          />
          {/* Shop price list mockup lines */}
          <line x1="18" y1="15" x2="30" y2="15" stroke="#ff4d79" strokeWidth="1.5" strokeLinecap="round" opacity="0.8" />
          <line x1="18" y1="20" x2="28" y2="20" stroke="#686882" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="18" y1="25" x2="31" y2="25" stroke="#686882" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="18" y1="30" x2="25" y2="30" stroke="#686882" strokeWidth="1.5" strokeLinecap="round" />
        </g>

        {/* --- Front Flipping Catalog Page --- */}
        <g className="paper-page-flip">
          <rect
            x="19"
            y="7"
            width="22"
            height="28"
            rx="3"
            fill="#1c1c27"
            stroke="#ff4d79"
            strokeWidth="1.3"
          />
          {/* Paper highlights & details */}
          <rect x="23" y="11" width="10" height="2" rx="1" fill="#ff7597" />
          <line x1="23" y1="17" x2="35" y2="17" stroke="#52526c" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="23" y1="22" x2="33" y2="22" stroke="#52526c" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="23" y1="27" x2="36" y2="27" stroke="#52526c" strokeWidth="1.5" strokeLinecap="round" />

          {/* Mini folded corner */}
          <path d="M37 7 L41 11 L37 11 Z" fill="#ff4d79" />
        </g>

        {/* --- Cute Animated Magnifying Glass Searching through Pages --- */}
        <g className="search-glass-move">
          {/* Glass Circle */}
          <circle
            cx="22"
            cy="24"
            r="8.5"
            fill="none"
            stroke="#ff4d79"
            strokeWidth="2.4"
            filter="url(#softGlow)"
          />
          <circle
            cx="22"
            cy="24"
            r="7"
            fill="#e9325a"
            fillOpacity="0.18"
          />
          {/* Lens glare highlight */}
          <path
            d="M18 20 A 5.5 5.5 0 0 1 24 18.5"
            stroke="#ffffff"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          {/* Glass Handle */}
          <line
            x1="28"
            y1="30"
            x2="35"
            y2="37"
            stroke="#ffffff"
            strokeWidth="2.8"
            strokeLinecap="round"
          />
          <line
            x1="28.5"
            y1="30.5"
            x2="34.5"
            y2="36.5"
            stroke="#ff4d79"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </g>

        {/* Sparkle star 1 */}
        <g className="sparkle-twinkle-1">
          <path
            d="M36 12 L37 15 L40 16 L37 17 L36 20 L35 17 L32 16 L35 15 Z"
            fill="#ffdd80"
          />
        </g>

        {/* Sparkle star 2 */}
        <g className="sparkle-twinkle-2">
          <circle cx="12" cy="11" r="1.5" fill="#ffffff" />
        </g>
      </svg>
    </div>
  );
};
