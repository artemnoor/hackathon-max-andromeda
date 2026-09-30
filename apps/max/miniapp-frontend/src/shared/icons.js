import Home01Icon from '@hugeicons/core-free-icons/Home01Icon';
import Search01Icon from '@hugeicons/core-free-icons/Search01Icon';
import GitCompareIcon from '@hugeicons/core-free-icons/GitCompareIcon';
import Target01Icon from '@hugeicons/core-free-icons/Target01Icon';
import Bookmark01Icon from '@hugeicons/core-free-icons/Bookmark01Icon';
import SparklesIcon from '@hugeicons/core-free-icons/SparklesIcon';
import StudentIcon from '@hugeicons/core-free-icons/StudentIcon';
import BookOpen01Icon from '@hugeicons/core-free-icons/BookOpen01Icon';
import MessageQuestionIcon from '@hugeicons/core-free-icons/MessageQuestionIcon';
import Cancel01Icon from '@hugeicons/core-free-icons/Cancel01Icon';

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';

const icons = Object.freeze({
  home: Home01Icon,
  search: Search01Icon,
  compare: GitCompareIcon,
  target: Target01Icon,
  bookmark: Bookmark01Icon,
  sparkles: SparklesIcon,
  student: StudentIcon,
  book: BookOpen01Icon,
  message: MessageQuestionIcon,
  close: Cancel01Icon,
});

function svgAttributeName(name) {
  return name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function createSvgIcon(definition) {
  const svg = document.createElementNS(SVG_NAMESPACE, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '24');
  svg.setAttribute('height', '24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.classList.add('hugeicon-svg');

  for (const [tagName, attributes] of definition) {
    const shape = document.createElementNS(SVG_NAMESPACE, tagName);
    for (const [name, value] of Object.entries(attributes)) {
      if (name !== 'key') shape.setAttribute(svgAttributeName(name), value);
    }
    svg.append(shape);
  }

  return svg;
}

export function mountHugeicons(root = globalThis.document) {
  root.querySelectorAll('[data-hugeicon]').forEach((container) => {
    const definition = icons[container.dataset.hugeicon];
    if (!definition) return;
    container.replaceChildren(createSvgIcon(definition));
  });
}
