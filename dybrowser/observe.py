"""ARIA snapshots plus ephemeral DOM handles; never modify the site's DOM."""
import json
import uuid
from .protocol import ToolError, require

COLLECT = r"""(root, limit) => {
  const elements = []; let scanned = 0, truncated = false;
  function walk(node) {
    if (scanned >= 20000) { truncated = true; return; }
    for (const e of node.children || []) {
      if (++scanned > 20000) { truncated = true; break; }
      const rect = e.getBoundingClientRect();
      if (e.matches('a[href],button,input,textarea,select,summary,[role],[tabindex],[contenteditable="true"]')
          && rect.width > 0 && rect.height > 0 && getComputedStyle(e).visibility !== 'hidden') {
        if (elements.length < limit) elements.push(e); else truncated = true;
      }
      if (e.shadowRoot) walk(e.shadowRoot);
      walk(e);
    }
  }
  // Start above body to include body itself when it is contenteditable.
  walk(root.parentElement || root);
  return {elements, truncated, scanned};
}"""

DESCRIBE = r"""(e) => {
  const r = e.getBoundingClientRect(), password = e.matches('input[type="password"]');
  const labels = e.labels ? Array.from(e.labels).map(l=>l.innerText).join(' ') : '';
  return {tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),
    name:e.getAttribute('aria-label') || labels || e.getAttribute('alt') || e.innerText?.slice(0,300) || '',
    text:(e.innerText || '').slice(0,300), type:e.getAttribute('type'),
    value:password ? null : ('value' in e ? String(e.value).slice(0,1000) : null),
    id:e.id || null, placeholder:e.getAttribute('placeholder'),
    href:e.getAttribute('href'), disabled:!!e.disabled,
    checked:typeof e.checked === 'boolean' ? e.checked : null,
    bounds:{x:r.x,y:r.y,width:r.width,height:r.height},
    in_viewport:r.bottom>0 && r.right>0 && r.x<innerWidth && r.y<innerHeight};
}"""

INSPECT = r"""(e, limit) => {
  const clone = e.cloneNode(true);
  if (clone.matches('input[type="password"]')) clone.removeAttribute('value');
  for (const p of clone.querySelectorAll('input[type="password"]')) p.removeAttribute('value');
  const html = clone.outerHTML;
  return {html:html.slice(0,limit), html_truncated:html.length>limit,
    text:(e.innerText || '').slice(0,limit)};
}"""


def scope(page, request):
    return page.frame_locator(request['frame']) if request.get('frame') else page


async def snapshot(session, page, options):
    pid = session.page_id(page)
    old = session.snapshots.pop(pid, None)
    if old:
        for h in old['refs'].values():
            await h.dispose()
    root = scope(page, options).locator('body')
    limit = options.get('max_chars', 20000)
    aria = await root.aria_snapshot(timeout=options.get('timeout', 10000))
    # Chromium/Playwright versions may include password values in ARIA text.
    # Read and redact without changing inputs or disturbing the website.
    secrets = await root.evaluate(r'''root => {
      const values=[];
      function walk(node) {
        for (const e of node.querySelectorAll('*')) {
          if (e.matches('input[type="password"]') && e.value) values.push(e.value);
          if (e.shadowRoot) walk(e.shadowRoot);
        }
      }
      walk(root); return values;
    }''')
    for secret in sorted(secrets, key=len, reverse=True):
        for form in (secret, json.dumps(secret, ensure_ascii=False)[1:-1], secret.replace("'", "''")):
            aria = aria.replace(form, '[redacted]')
    collection = await root.evaluate_handle(COLLECT, options.get('max_elements', 200))
    refs, elements = {}, []
    try:
        meta = await collection.evaluate('(v)=>({truncated:v.truncated,scanned:v.scanned})')
        array = await collection.get_property('elements')
        try:
            props = await array.get_properties()
            for key, handle in props.items():
                element = handle.as_element()
                if element:
                    ref = f'e{len(refs)+1}'
                    refs[ref] = element
                    info = await element.evaluate(DESCRIBE)
                    elements.append({'ref': ref, **info})
                else:
                    await handle.dispose()
        finally:
            await array.dispose()
    except Exception:
        for h in refs.values():
            await h.dispose()
        raise
    finally:
        await collection.dispose()
    sid = uuid.uuid4().hex[:16]
    session.snapshots[pid] = {'id': sid, 'refs': refs}
    return {'page_id': pid, 'snapshot_id': sid, 'url': page.url,
            'title': await page.title(), 'aria': aria[:limit],
            'elements': elements, 'truncated': meta['truncated'] or len(aria) > limit,
            'aria_truncated': len(aria) > limit, 'elements_truncated': meta['truncated'],
            'frames': [{'name': f.name, 'url': f.url} for f in page.frames if f != page.main_frame],
            'frame': options.get('frame'), 'coordinate_space': 'viewport_css_pixels'}


async def resolve_locator(session, page, options, *, allow_missing=False):
    if 'ref' in options:
        snap = session.snapshots.get(session.page_id(page))
        require(snap is not None and snap['id'] == options['snapshot_id'],
                'Snapshot expired; request a new snapshot', 'stale_reference')
        element = snap['refs'].get(options['ref'])
        require(element is not None, 'Unknown ref; request a new snapshot', 'stale_reference')
        try:
            connected = await element.evaluate('(e)=>e.isConnected')
        except Exception:
            connected = False
        require(connected, 'Element detached; request a new snapshot', 'stale_reference')
        return element
    base = scope(page, options)
    exact = options.get('exact', True)
    if 'role' in options:
        kwargs = {'name': options['name'], 'exact': exact} if 'name' in options else {}
        locator = base.get_by_role(options['role'], **kwargs)
    elif 'label' in options:
        locator = base.get_by_label(options['label'], exact=exact)
    elif 'css' in options:
        locator = base.locator(options['css'])
    elif 'text' in options:
        locator = base.get_by_text(options['text'], exact=exact)
    else:
        raise ToolError('invalid_request', 'An element locator is required')
    count = await locator.count()
    if 'nth' in options:
        return locator.nth(options['nth'])
    require(count <= 1, f'Locator matches {count} elements; narrow it or specify nth', 'ambiguous_locator')
    if not allow_missing and count == 0:
        # Let Playwright wait for a dynamically appearing element.
        await locator.wait_for(state='attached', timeout=options.get('timeout', 10000))
        require(await locator.count() == 1, 'Locator became ambiguous', 'ambiguous_locator')
    return locator


async def inspect(session, page, request):
    target = await resolve_locator(session, page, request)
    data = await target.evaluate(DESCRIBE)
    data.update(await target.evaluate(INSPECT, request.get('max_chars', 10000)))
    data['page_id'] = session.page_id(page)
    return data
