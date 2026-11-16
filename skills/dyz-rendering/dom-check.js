// 只检查当前预览DOM；不导航、不联网，不把几何检查当作专业签核。
() => {
  const issues = [];
  const tolerance = 1;
  const outside = (inner, outer) => inner.left < outer.left - tolerance ||
    inner.top < outer.top - tolerance || inner.right > outer.right + tolerance ||
    inner.bottom > outer.bottom + tolerance;
  const main = document.querySelector('main');
  if (!main) return {status: 'failed', issues: ['preview_main_missing'], notes: '不是指定预览页面'};
  if (document.documentElement.scrollWidth > window.innerWidth + tolerance)
    issues.push({code: 'document_horizontal_overflow'});
  for (const element of main.querySelectorAll('p, h1, h2, h3, h4, h5, h6, td, th, pre, .source-text')) {
    if (element.scrollWidth > element.clientWidth + tolerance && element.clientWidth > 0)
      issues.push({code: 'text_overflow', tag: element.tagName});
  }
  for (const svg of main.querySelectorAll('svg')) {
    const bounds = svg.getBoundingClientRect();
    const rects = [...svg.querySelectorAll('rect')].filter(r => !r.closest('defs, marker'));
    for (const element of svg.querySelectorAll('path, rect, text, tspan, circle, ellipse, line, polyline, polygon')) {
      if (element.closest('defs, marker')) continue;
      const box = element.getBoundingClientRect();
      if (outside(box, bounds)) issues.push({code: 'svg_outside_viewbox', tag: element.tagName,
        text: element.textContent, bounds: box.toJSON(), viewport: bounds.toJSON()});
      if (element.tagName === 'text') {
        const style = getComputedStyle(element);
        if (style.fill === 'none' || style.fill === 'transparent' || style.fontSize === '0px' ||
            style.visibility !== 'visible' || style.display === 'none' || Number(style.opacity) === 0)
          issues.push({code: 'svg_text_not_visible', text: element.textContent});
        const origin = svg.createSVGPoint();
        origin.x = element.x.baseVal.numberOfItems ? element.x.baseVal.getItem(0).value : 0;
        origin.y = element.y.baseVal.numberOfItems ? element.y.baseVal.getItem(0).value : 0;
        const anchor = origin.matrixTransform(element.getScreenCTM());
        const owner = rects.find(rect => {
          const r = rect.getBoundingClientRect();
          return anchor.x >= r.left && anchor.x <= r.right && anchor.y >= r.top && anchor.y <= r.bottom;
        });
        if (owner && outside(box, owner.getBoundingClientRect()))
          issues.push({code: 'svg_label_outside_node', text: element.textContent,
            bounds: box.toJSON(), node: owner.getBoundingClientRect().toJSON()});
      }
    }
  }
  const sourceLines = [...main.querySelectorAll('.source-line')].map(line => ({
    line: Number(line.dataset.line), text: line.querySelector('.source-text').textContent
  }));
  const pages = [...main.querySelectorAll('.source-page')].map(page => ({
    page: Number(page.dataset.page), rows: page.querySelectorAll('.source-line').length,
    bounds: page.getBoundingClientRect().toJSON()
  }));
  if (pages.some(page => page.rows > 40)) issues.push({code: 'logical_page_row_limit'});
  return {status: issues.length ? 'failed' : 'passed', issues,
    notes: '屏幕DOM几何检查：文档水平溢出、SVG实际字形/图形viewBox和节点矩形边界、文本可见性、逻辑页行数；不替代肉眼、官方页式或语义核验。',
    viewport: {width: window.innerWidth, height: window.innerHeight},
    userAgent: navigator.userAgent, mainText: main.innerText, sourceLines, pages,
    headings: main.querySelectorAll('h1,h2,h3,h4,h5,h6').length,
    tables: main.querySelectorAll('table').length,
    rows: main.querySelectorAll('tbody tr').length,
    svgTextCount: main.querySelectorAll('svg text').length,
    svgSize: [...main.querySelectorAll('svg')].map(s => s.getBoundingClientRect().toJSON())};
}
