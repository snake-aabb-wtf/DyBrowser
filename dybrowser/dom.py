"""Bounded, read-only DOM subtree collection, including ordinary text nodes."""

COLLECT_DOM = r"""(root, options) => {
  const elements = [], reasons = new Set();
  const allowed = new Set(['id','class','role','title','href','src','alt','name',
    'type','placeholder','datetime','for','value','contenteditable','tabindex']);
  let count = 0, scanned = 0, chars = 0;
  const cut = reason => reasons.add(reason);
  function text(value) {
    const available = Math.max(0, options.max_chars - chars);
    if (value.length > available) cut('max_chars');
    const result = value.slice(0, available);
    chars += result.length;
    return result;
  }
  function walk(node, depth, ancestorHidden = false) {
    if (++scanned > 20000) { cut('scan_limit'); return null; }
    if (node.nodeType === Node.TEXT_NODE) {
      const value = node.nodeValue.trim();
      if (!value) return null;
      if (count >= options.max_nodes) { cut('max_nodes'); return null; }
      count++;
      return {type:'text', text:text(value)};
    }
    const shadow = node.nodeType === Node.DOCUMENT_FRAGMENT_NODE;
    if (!shadow && node.nodeType !== Node.ELEMENT_NODE) return null;
    if (!shadow && node.matches('script,style,noscript,template')) return null;
    const style = shadow ? null : getComputedStyle(node);
    const hidden = ancestorHidden || (style && (style.display === 'none' || style.visibility === 'hidden'));
    if (hidden && !options.include_hidden) return null;
    if (count >= options.max_nodes) { cut('max_nodes'); return null; }
    count++;
    const result = {type:shadow ? 'shadow-root' : 'element',
      tag:shadow ? '#shadow-root' : node.tagName.toLowerCase(), children:[]};
    if (!shadow) {
      elements.push(node);
      result.ref = 'e' + elements.length;
      result.attributes = {};
      result.visible = !hidden;
      const password = node.matches('input[type="password"]');
      let attributes = 0;
      for (const attr of node.attributes) {
        if (!(allowed.has(attr.name) || attr.name.startsWith('data-') || attr.name.startsWith('aria-'))) continue;
        if (password && attr.name === 'value') continue;
        if (++attributes > 50) { cut('attribute_limit'); break; }
        result.attributes[attr.name] = text(attr.value);
      }
      const r = node.getBoundingClientRect();
      result.bounds = {x:r.x,y:r.y,width:r.width,height:r.height};
    }
    function* children() {
      yield* node.childNodes;
      if (!shadow && node.shadowRoot) yield node.shadowRoot;
    }
    if (depth >= options.max_depth) {
      if (node.childNodes.length || (!shadow && node.shadowRoot)) cut('max_depth');
      return result;
    }
    for (const child of children()) {
      if (scanned >= 20000) { cut('scan_limit'); break; }
      if (child.nodeType === Node.TEXT_NODE && !child.nodeValue.trim()) {
        scanned++;
        continue;
      }
      if (count >= options.max_nodes) {
        cut('max_nodes');
        break;
      }
      const item = walk(child, depth + 1, hidden);
      if (item) result.children.push(item);
    }
    return result;
  }
  let ancestorHidden = false;
  function parent(node) {
    return node.parentElement || node.getRootNode().host || null;
  }
  for (let p = parent(root); p; p = parent(p)) {
    const style = getComputedStyle(p);
    if (style.display === 'none' || style.visibility === 'hidden') ancestorHidden = true;
  }
  const dom = walk(root, 0, ancestorHidden);
  return {elements, dom, truncated:reasons.size > 0, reasons:[...reasons],
    node_count:count, scanned, chars};
}"""
