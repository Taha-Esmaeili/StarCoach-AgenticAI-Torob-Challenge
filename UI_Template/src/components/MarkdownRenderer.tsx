import React from 'react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

/**
 * Enhanced Persian Markdown Parser & Renderer
 * Accurately parses bold, italic, strikethrough, horizontal rules (---, ***),
 * headers, bullet lists, Persian & English numbered lists (۱., 1.),
 * blockquotes, links, and code spans without raw syntax leaks.
 */
export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className = '',
}) => {
  if (!content) return null;

  // Helper to parse inline markdown (bold, italic, strikethrough, code, links)
  const renderInline = (text: string): React.ReactNode => {
    // Regex matching:
    // 1: **bold** or __bold__
    // 2: *italic* or _italic_
    // 3: ~~strikethrough~~
    // 4: `code`
    // 5: [link](url)
    const regex = /(\*\*([^*]+)\*\*|__([^_]+)__|(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)|~~([^~]+)~~|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g;

    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    let keyIdx = 0;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index));
      }

      if (match[2] || match[3]) {
        // Bold
        parts.push(
          <strong key={`b-${keyIdx++}`} className="font-extrabold text-white">
            {match[2] || match[3]}
          </strong>
        );
      } else if (match[4] || match[5]) {
        // Italic
        parts.push(
          <em key={`em-${keyIdx++}`} className="italic text-[#ff80a0]">
            {match[4] || match[5]}
          </em>
        );
      } else if (match[6]) {
        // Strikethrough
        parts.push(
          <del key={`del-${keyIdx++}`} className="line-through text-neutral-500">
            {match[6]}
          </del>
        );
      } else if (match[7]) {
        // Inline code
        parts.push(
          <code
            key={`code-${keyIdx++}`}
            className="px-1.5 py-0.5 rounded bg-[#1e1e28] text-[#ff6688] font-mono text-xs sm:text-[13px] border border-[#2c2c3e]"
          >
            {match[7]}
          </code>
        );
      } else if (match[8] && match[9]) {
        // Link
        parts.push(
          <a
            key={`a-${keyIdx++}`}
            href={match[9]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#ff4d79] hover:underline font-bold"
          >
            {match[8]}
          </a>
        );
      }

      lastIndex = regex.lastIndex;
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : text;
  };

  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let currentList: { type: 'ul' | 'ol'; items: string[] } | null = null;
  let currentParagraphLines: string[] = [];

  const flushParagraph = () => {
    if (currentParagraphLines.length === 0) return;
    const key = `p-${elements.length}`;
    elements.push(
      <p key={key} className="leading-relaxed my-1.5">
        {currentParagraphLines.map((line, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <br />}
            {renderInline(line)}
          </React.Fragment>
        ))}
      </p>
    );
    currentParagraphLines = [];
  };

  const flushList = () => {
    if (!currentList) return;
    if (currentList.type === 'ul') {
      elements.push(
        <ul key={`ul-${elements.length}`} className="my-2 space-y-1.5 pr-2">
          {currentList.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 text-neutral-200">
              <span className="w-1.5 h-1.5 rounded-full bg-[#ff4d79] mt-2 shrink-0" />
              <div className="flex-1 leading-relaxed">{renderInline(item)}</div>
            </li>
          ))}
        </ul>
      );
    } else {
      elements.push(
        <ol key={`ol-${elements.length}`} className="my-2 space-y-1.5 pr-2">
          {currentList.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 text-neutral-200">
              <span className="text-sm font-bold text-[#ff6688] mt-0.5 shrink-0">
                {(idx + 1).toLocaleString('fa-IR')}.
              </span>
              <div className="flex-1 leading-relaxed">{renderInline(item)}</div>
            </li>
          ))}
        </ol>
      );
    }
    currentList = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // Empty line -> flush list and paragraph
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    // Horizontal Rule: --- or *** or ___
    if (/^(\*{3,}|-{3,}|_{3,})$/.test(trimmed)) {
      flushParagraph();
      flushList();
      elements.push(
        <hr key={`hr-${i}`} className="my-3 border-t border-[#2e2e42]" />
      );
      continue;
    }

    // Blockquote: > text
    const blockquoteMatch = trimmed.match(/^>\s*(.*)$/);
    if (blockquoteMatch) {
      flushParagraph();
      flushList();
      elements.push(
        <blockquote
          key={`bq-${i}`}
          className="border-r-2 border-[#e9325a] pr-3 my-2 text-neutral-200 italic bg-[#161622]/60 py-2 rounded-l text-[13px] sm:text-sm"
        >
          {renderInline(blockquoteMatch[1])}
        </blockquote>
      );
      continue;
    }

    // Bullet List: - item, * item, • item, ▪ item
    const bulletMatch = trimmed.match(/^[-*•▪▫]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      if (!currentList || currentList.type !== 'ul') {
        flushList();
        currentList = { type: 'ul', items: [] };
      }
      currentList.items.push(bulletMatch[1]);
      continue;
    }

    // Numbered List: Persian (۱. , ۱) ) or English (1. , 1) )
    const numberMatch = trimmed.match(/^(\d+|[۰-۹]+)[.)]\s+(.*)$/);
    if (numberMatch) {
      flushParagraph();
      if (!currentList || currentList.type !== 'ol') {
        flushList();
        currentList = { type: 'ol', items: [] };
      }
      currentList.items.push(numberMatch[2]);
      continue;
    }

    // Headers: # H1, ## H2, ### H3
    const headerMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (headerMatch) {
      flushParagraph();
      flushList();
      const level = headerMatch[1].length;
      const text = headerMatch[2];
      if (level === 1) {
        elements.push(
          <h2
            key={`h1-${i}`}
            className="text-base md:text-lg font-black text-white mt-3 mb-1.5 border-b border-[#252536] pb-1"
          >
            {renderInline(text)}
          </h2>
        );
      } else if (level === 2) {
        elements.push(
          <h3
            key={`h2-${i}`}
            className="text-sm md:text-base font-extrabold text-[#ff6688] mt-2.5 mb-1"
          >
            {renderInline(text)}
          </h3>
        );
      } else {
        elements.push(
          <h4
            key={`h3-${i}`}
            className="text-sm font-bold text-neutral-100 mt-2 mb-0.5"
          >
            {renderInline(text)}
          </h4>
        );
      }
      continue;
    }

    // Non-empty line inside paragraph
    flushList();
    currentParagraphLines.push(trimmed);
  }

  flushParagraph();
  flushList();

  return <div className={`text-neutral-200 ${className}`}>{elements}</div>;
};
