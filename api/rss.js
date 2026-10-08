const dns = require('dns').promises;
const net = require('net');
const { auth } = require('./_lib');

// Addresses a public feed can never be on: loopback, private ranges, link-local (cloud metadata), CGNAT, ULA.
function privateIp(ip) {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split('.').map(Number);
    return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || a >= 224;
  }
  const s = ip.toLowerCase();
  return s === '::1' || s === '::' || s.startsWith('fc') || s.startsWith('fd') || s.startsWith('fe80') || s.startsWith('::ffff:') && privateIp(s.slice(7));
}
// Fetches a public https URL without ever reaching an internal address, following at most 3 redirects, each checked.
async function safeFetch(u, opts, hops = 0) {
  if (!allowed(u)) throw new Error('blocked');
  const host = new URL(u).hostname;
  const addrs = await dns.lookup(host, { all: true });
  if (!addrs.length || addrs.some((a) => privateIp(a.address))) throw new Error('blocked');
  const r = await fetch(u, Object.assign({}, opts, { redirect: 'manual' }));
  if ([301, 302, 303, 307, 308].includes(r.status)) {
    if (hops >= 3) throw new Error('too many redirects');
    return safeFetch(new URL(r.headers.get('location') || '', u).href, opts, hops + 1);
  }
  return r;
}

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
  if (!(await auth(req, res))) return;
  const u = String((req.query || {}).url || '');
  if (!allowed(u)) return res.status(400).json({ error: 'Use a public https:// feed address.' });
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 9000);
  try {
    const r = await safeFetch(u, { signal: ctl.signal, headers: { 'User-Agent': 'parcours-personal-search-app', Accept: 'application/rss+xml, application/atom+xml, text/xml, */*' } });
    if (!r.ok) return res.status(502).json({ error: 'The feed answered with HTTP ' + r.status + '.' });
    const text = (await r.text()).slice(0, 1500000);
    const items = parseFeed(text);
    if (!items.length) return res.status(422).json({ error: 'No items found. Check that this is an RSS or Atom feed.' });
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).json({ items });
  } catch (e) {
    res.status(e.message === 'blocked' ? 400 : 502).json({ error: e.name === 'AbortError' ? 'The feed took too long to answer.' : e.message === 'blocked' ? 'Use a public https:// feed address.' : 'Could not read the feed.' });
  } finally { clearTimeout(t); }
};

module.exports._test = { parseFeed, allowed, privateIp };
