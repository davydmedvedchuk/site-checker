// Site checker rules for the web page. Same rules and ids as cli/sitecheck.py (tests/expected.json holds what both must find).
// Pure function: HTML text in, list of issues out. Runs in the browser, nothing is sent anywhere.
(function (root) {
  const LEVEL_ORDER = { error: 0, warn: 1, info: 2 }, WEIGHT = { error: 12, warn: 5, info: 1 };
  const plural = (n, w) => `${n} ${w}${n > 1 ? 's' : ''}`;
  const snip = (e) => {
    const keep = ['src', 'href', 'name', 'id', 'type'].filter(k => e.hasAttribute(k)).map(k => `${k}="${e.getAttribute(k).slice(0, 40)}"`).join(' ');
    return `<${e.tagName.toLowerCase()}${keep ? ' ' + keep : ''}>`;
  };

  function check(html, base) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const out = [];
    const add = (id, level, title, fix, items = []) => out.push({ id, level, title, fix, count: items.length || 1, examples: items.slice(0, 3).map(x => typeof x === 'string' ? x : snip(x)) });
    const all = [...doc.querySelectorAll('*')];
    const $$ = (s) => [...doc.querySelectorAll(s)];
    const meta = (n) => $$('meta').find(m => (m.getAttribute('name') || '').toLowerCase() === n);
    const has = (e, a) => e.hasAttribute(a);
    const val = (e, a) => (e.getAttribute(a) || '').trim();

    const ttl = (doc.querySelector('title')?.textContent || '').trim();
    if (!ttl) add('title-missing', 'error', 'The page has no title', 'Add a <title> of about 30 to 60 characters. It is the headline in search results and browser tabs.');
    else if (ttl.length > 60) add('title-long', 'info', `The title is ${ttl.length} characters`, 'Keep it under about 60 characters, or search engines cut it off.');

    const dm = meta('description'), dc = dm ? val(dm, 'content') : '';
    if (!dc) add('description-missing', 'warn', 'No meta description', 'Add <meta name="description" content="…"> with one clear sentence (up to 160 characters).');
    else if (dc.length > 160) add('description-long', 'info', `The description is ${dc.length} characters`, 'Shorten it to 160 or less so it is not cut off.');

    const lang = doc.documentElement.hasAttribute('lang') && (doc.documentElement.getAttribute('lang') || '').trim();
    if (!lang) add('lang-missing', 'warn', 'The <html> tag has no lang', 'Write <html lang="en"> (or pt, ru…). Screen readers and translators need it.');
    if (!meta('viewport')) add('viewport-missing', 'error', 'No mobile viewport', 'Add <meta name="viewport" content="width=device-width, initial-scale=1">. Without it phones show a tiny desktop page.');

    const h1 = $$('h1');
    if (!h1.length) add('h1-missing', 'warn', 'No <h1> heading', 'Give the page one main heading that says what it is about.');
    else if (h1.length > 1) add('h1-multiple', 'info', `${h1.length} <h1> headings`, 'Use one <h1> and make the others <h2>.', h1);

    const imgs = $$('img');
    const bad = imgs.filter(i => !has(i, 'alt') && i.getAttribute('aria-hidden') !== 'true' && !['presentation', 'none'].includes(i.getAttribute('role')));
    if (bad.length) add('img-alt-missing', 'error', `${plural(bad.length, 'image')} without alt text`, 'Describe each image in alt="…". For pure decoration write alt="" on purpose.', bad);
    const nosize = imgs.filter(i => !(has(i, 'width') && has(i, 'height')));
    if (nosize.length) add('img-size-missing', 'warn', `${plural(nosize.length, 'image')} without width and height`, 'Add width and height so the page does not jump while images load.', nosize);
    const lazy = imgs.slice(2).filter(i => (i.getAttribute('loading') || '').toLowerCase() !== 'lazy');
    if (lazy.length) add('img-lazy-missing', 'info', `${plural(lazy.length, 'image')} load right away`, 'Add loading="lazy" to images below the first screen.', lazy);

    const blocking = $$('head script[src]').filter(s => !has(s, 'defer') && !has(s, 'async') && (s.getAttribute('type') || '').toLowerCase() !== 'module');
    if (blocking.length) add('script-blocking', 'warn', (blocking.length > 1 ? `${blocking.length} scripts block the page` : '1 script blocks the page'), 'Add defer to scripts in the <head> so the page can show first.', blocking);

    const empty = $$('a[href]').filter(a => !(((a.textContent || '') + ' ' + [...a.querySelectorAll('img')].map(i => i.getAttribute('alt') || '').join(' ')).trim() || val(a, 'aria-label') || val(a, 'title')));
    if (empty.length) add('link-empty', 'warn', `${plural(empty.length, 'link')} with no text`, 'Give each link text or aria-label so people using a screen reader know where it goes.', empty);

    const labelFor = new Set($$('label[for]').map(l => l.getAttribute('for')).filter(Boolean));
    const nolabel = $$('input, select, textarea').filter(i =>
      (i.tagName !== 'INPUT' || !['hidden', 'submit', 'button', 'image', 'reset'].includes((i.getAttribute('type') || 'text').toLowerCase())) &&
      !(val(i, 'aria-label') || val(i, 'aria-labelledby') || val(i, 'title') || i.closest('label') || (i.id && labelFor.has(i.id))));
    if (nolabel.length) add('input-label-missing', 'warn', `${plural(nolabel.length, 'form field')} without a label`, 'Connect each field to a <label for=…>, or add aria-label.', nolabel);

    const rel = (e) => (e.getAttribute('rel') || '').toLowerCase().split(/\s+/);
    const links = $$('link');
    if (!links.some(l => rel(l).includes('canonical'))) add('canonical-missing', 'info', 'No canonical link', 'Add <link rel="canonical" href="…"> so search engines know the main address.');
    const props = new Set($$('meta').map(m => (m.getAttribute('property') || '').toLowerCase()));
    if (!(props.has('og:title') && props.has('og:image'))) add('og-missing', 'info', 'Link preview is incomplete (og:title or og:image missing)', 'Add og:title and og:image meta tags so the page looks right when shared in WhatsApp, Telegram or LinkedIn.');
    if (!links.some(l => rel(l).includes('icon') || rel(l).some(r => r.includes('icon')))) add('favicon-missing', 'info', 'No favicon', 'Add <link rel="icon" href="…">. Browsers ask for one anyway.');

    let last = 0; const skips = [];
    for (const e of all) { if (/^H[1-6]$/.test(e.tagName)) { const n = +e.tagName[1]; if (last && n > last + 1) skips.push(e); last = n; } }
    if (skips.length) add('heading-skip', 'info', `Heading levels jump (${skips.length}×)`, 'Do not skip levels, for example h1 straight to h3. Screen readers use them as an outline.', skips);

    if (base && /^https:\/\//i.test(base)) {
      const http = (v) => /^http:\/\//i.test(v || '');
      const mixed = all.filter(e => (['IMG', 'SCRIPT', 'IFRAME', 'SOURCE'].includes(e.tagName) && http(e.getAttribute('src'))) || (e.tagName === 'LINK' && rel(e).includes('stylesheet') && http(e.getAttribute('href'))));
      if (mixed.length) add('mixed-content', 'error', `${plural(mixed.length, 'resource')} loaded over http on an https page`, 'Change http:// to https://. Browsers block or warn about these.', mixed);
    }
    out.sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]);
    return out;
  }
  const score = (issues) => Math.max(0, 100 - issues.reduce((s, i) => s + WEIGHT[i.level], 0));
  root.SiteCheck = { check, score };
})(typeof window !== 'undefined' ? window : globalThis);
