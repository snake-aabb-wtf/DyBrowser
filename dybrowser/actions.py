"""Browser actions dispatched only after protocol validation."""
import asyncio
from pathlib import Path
import struct
import uuid

from .protocol import ToolError, require
from .observe import snapshot, inspect, resolve_locator


async def execute(session, request, root):
    action = request['action']
    timeout = request.get('timeout', 10000)
    if action == 'pages':
        return session.info()
    if action == 'page_new':
        page = await session.context.new_page()
        session.current = session.page_id(page)
        if request.get('url'):
            await page.goto(request['url'], timeout=request.get('timeout', 30000))
        return {'page_id': session.current, 'url': page.url}
    page = session.page(request.get('page_id'))
    pid = session.page_id(page)
    result = {'page_id': pid}
    if action == 'page_switch':
        session.current = pid
        await page.bring_to_front()
    elif action == 'page_close':
        await page.close()
        result['current_page_id'] = session.current
    elif action in ('goto', 'back', 'forward', 'reload'):
        kwargs = {'timeout': request.get('timeout', 30000),
                  'wait_until': request.get('wait_until', 'domcontentloaded')}
        if action == 'goto':
            response = await page.goto(request['url'], **kwargs)
        else:
            response = await getattr(page, {'back':'go_back','forward':'go_forward',
                                           'reload':'reload'}[action])(**kwargs)
        result.update(url=page.url, status=response.status if response else None)
    elif action == 'snapshot':
        return await snapshot(session, page, request)
    elif action in ('inspect', 'text'):
        data = await inspect(session, page, request)
        return data if action == 'inspect' else {'page_id': pid, 'text': data['text']}
    elif action == 'screenshot':
        folder = Path(root) / 'artifacts' / session.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{uuid.uuid4().hex}.png'
        png = await page.screenshot(path=str(path), full_page=request.get('full_page', False), timeout=timeout)
        width, height = struct.unpack('>II', png[16:24])
        result.update(path=str(path.resolve()), width=width, height=height,
                      full_page=request.get('full_page', False),
                      coordinate_space='document_image_pixels' if request.get('full_page') else 'viewport_css_pixels',
                      viewport=page.viewport_size, device_scale_factor=await page.evaluate('devicePixelRatio'))
    elif action == 'click_xy':
        size = page.viewport_size
        require(size and 0 <= request['x'] < size['width'] and 0 <= request['y'] < size['height'],
                'Coordinates must be inside the viewport')
        await page.mouse.click(request['x'], request['y'], button=request.get('button', 'left'))
    elif action == 'scroll':
        await page.mouse.wheel(request.get('x', 0), request.get('y', 600))
        # Wheel dispatch itself does not await the next rendered frame.
        await page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
    elif action == 'evaluate':
        try:
            result['result'] = await asyncio.wait_for(
                page.evaluate(request['expression'], request.get('arg')), timeout/1000)
        except asyncio.TimeoutError as exc:
            raise ToolError('timeout', 'JavaScript evaluation timed out') from exc
    elif action == 'wait':
        if 'ms' in request:
            await asyncio.sleep(request['ms']/1000)
        elif 'url' in request:
            await page.wait_for_url(request['url'], timeout=timeout)
        else:
            target = await resolve_locator(session, page, request, allow_missing=True)
            if 'ref' in request:
                state = request.get('state', 'visible')
                require(state != 'detached', 'Use a locator to wait for detached state')
                if state != 'attached':
                    await target.wait_for_element_state(state, timeout=timeout)
            else:
                await target.wait_for(state=request.get('state', 'visible'), timeout=timeout)
    elif action == 'press' and not any(k in request for k in ('ref','role','label','css','text')):
        await page.keyboard.press(request['key'])
    else:
        target = await resolve_locator(session, page, request)
        if action == 'click':
            await target.click(timeout=timeout, button=request.get('button', 'left'))
        elif action == 'fill':
            await target.fill(request['text'], timeout=timeout)
        elif action == 'type':
            if 'ref' in request:
                await target.type(request['text'], timeout=timeout)
            else:
                await target.press_sequentially(request['text'], timeout=timeout)
        elif action == 'press':
            await target.press(request['key'], timeout=timeout)
        elif action == 'select_option':
            result['values'] = await target.select_option(request['value'], timeout=timeout)
        else:
            await getattr(target, action)(timeout=timeout)
    return result
