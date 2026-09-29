const { auth } = require('./_lib');

const decode = (s) => String(s || '')
  .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
  .replace(/<[^>]+>/g, ' ')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
  .replace(/&#(\d+);/g, (m, n) => String.fromCharCode(+n)).replace(/&amp;/g, '&')
  .replace(/\s+/g, ' ').trim();
const tag = (block, name) => {
  const m = block.match(new RegExp('<' + name + '[^>]*>([\\s\\S]*?)</' + name + '>', 'i'));
  return m ? m[1] : '';
};

function parseFeed(xml) {
  const blocks = xml.match(/<item[\s>][\s\S]*?<\/item>|<entry[\s>][\s\S]*?<\/entry>/gi) || [];
  return blocks.slice(0, 30).map((b) => {
    let link = decode(tag(b, 'link'));
    if (!link) { const m = b.match(/<link[^>]*href=["']([^"']+)["']/i); link = m ? m[1] : ''; }
    return {
      title: decode(tag(b, 'title')), link,
      date: decode(tag(b, 'pubDate') || tag(b, 'published') || tag(b, 'updated') || tag(b, 'dc:date')),
      summary: decode(tag(b, 'description') || tag(b, 'summary') || tag(b, 'content')).slice(0, 220)
    };
  }).filter((i) => i.title && /^https?:\/\//i.test(i.link));
}

function allowed(u) {
  let url;
  try { url = new URL(u); } catch (e) { return false; }
  if (url.protocol !== 'https:') return false;
  const h = url.hostname.toLowerCase();
  if (h === 'localhost' || h.endsWith('.local') || h.endsWith('.internal') || h.includes(':') || /^\d+\.\d+\.\d+\.\d+$/.test(h)) return false;
  return true;
}

module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const u = String((req.query || {}).url || '');
  if (!allowed(u)) return res.status(400).json({ error: 'Use a public https:// feed address.' });
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 9000);
  try {
    const r = await fetch(u, { signal: ctl.signal, headers: { 'User-Agent': 'parcours-personal-search-app', Accept: 'application/rss+xml, application/atom+xml, text/xml, */*' } });
    if (!r.ok) return res.status(502).json({ error: 'The feed answered with HTTP ' + r.status + '.' });
    const text = (await r.text()).slice(0, 1500000);
    const items = parseFeed(text);
    if (!items.length) return res.status(422).json({ error: 'No items found. Check that this is an RSS or Atom feed.' });
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).json({ items });
  } catch (e) {
    res.status(502).json({ error: e.name === 'AbortError' ? 'The feed took too long to answer.' : 'Could not read the feed.' });
  } finally { clearTimeout(t); }
};

module.exports._test = { parseFeed, allowed };
