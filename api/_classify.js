// Free, rule-based sorting of job-search emails (EN, FR, DE). No AI, no API calls.
// Approach follows open-source trackers such as CareerSync (MIT) and job-tracker: phrase rules
// checked in priority order (rejection, offer, interview, confirmation, opportunity), plus
// sender-domain hints for recruiting systems and job boards. The user reviews every result.

const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[‘’´`]/g, "'").replace(/\s+/g, ' ');

// Each rule: [label, phrases]. Phrases are matched against normalised subject + body.
const RULES = {
  rejected: [
    'unfortunately', 'regret to inform', 'not to move forward', 'not moving forward', 'will not be moving forward',
    'won\'t be moving forward', 'decided to move forward with other', 'decided to proceed with other', 'pursue other candidates',
    'other candidates whose', 'position has been filled', 'role has been filled', 'not been selected', 'were not selected',
    'unable to offer you', 'not be progressing', 'won\'t be progressing', 'not be proceeding', 'no longer under consideration',
    'we will not be able to offer', 'not successful on this occasion', 'your application was unsuccessful',
    'malheureusement', 'nous regrettons', 'avons le regret', 'ne pas donner suite', 'ne pouvons pas donner suite',
    'pas pu donner une suite favorable', 'suite defavorable', 'reponse negative', 'pas ete retenu', 'n\'avez pas ete retenu',
    'n\'a pas ete retenue', 'pas ete selectionne', 'ne correspond pas a nos besoins', 'autres candidats',
    'leider', 'absage', 'nicht berucksichtigen', 'nicht weiter berucksichtigen', 'fur einen anderen kandidaten', 'anderen bewerber'
  ],
  offer: [
    'pleased to offer', 'delighted to offer', 'happy to offer', 'offer letter', 'offer of employment', 'extend an offer',
    'extend you an offer', 'formal offer', 'you have been admitted', 'you have been accepted', 'offer of admission',
    'admission offer', 'we are pleased to admit', 'congratulations on your admission', 'accepted into the',
    'promesse d\'embauche', 'proposition d\'embauche', 'proposition de contrat', 'plaisir de vous proposer le poste',
    'plaisir de vous annoncer', 'vous etes admis', 'vous avez ete admis', 'votre admission', 'avis favorable',
    'zusage', 'vertragsangebot', 'freuen uns, ihnen', 'arbeitsvertrag', 'zulassungsbescheid', 'sie wurden zugelassen'
  ],
  interview: [
    'interview', 'phone screen', 'phone call with', 'schedule a call', 'schedule a time', 'book a time', 'your availability',
    'availabilities', 'next round', 'next step in the process', 'next stage', 'assessment', 'coding challenge', 'technical test',
    'take-home', 'home assignment', 'hackerrank', 'codility', 'codingame', 'testgorilla', 'hirevue', 'calendly.com',
    'entretien', 'echange telephonique', 'vos disponibilites', 'test technique', 'etude de cas', 'vous rencontrer',
    'prochaine etape', 'vorstellungsgesprach', 'kennenlernen', 'personliches gesprach', 'telefoninterview', 'einladung zum'
  ],
  applied: [
    'thank you for applying', 'thanks for applying', 'thank you for your application', 'thanks for your application',
    'application received', 'received your application', 'application has been received', 'application was submitted',
    'application submitted', 'successfully applied', 'your application to', 'your application for', 'we will review your application',
    'reviewing your application', 'thank you for your interest in',
    'bien recu votre candidature', 'votre candidature a bien ete', 'merci pour votre candidature', 'merci de votre candidature',
    'accuse de reception', 'candidature a ete transmise', 'candidature envoyee', 'nous etudions votre candidature',
    'vielen dank fur ihre bewerbung', 'danke fur ihre bewerbung', 'eingang ihrer bewerbung', 'bewerbung erhalten', 'bewerbung ist eingegangen'
  ],
  opportunity: [
    'job alert', 'jobs for you', 'new jobs', 'jobs matching', 'jobs that match', 'recommended jobs', 'recommended for you',
    'new opportunities', 'job opportunity', 'came across your profile', 'your profile caught', 'would you be interested',
    'are you open to', 'open to new opportunities', 'great fit for', 'we are hiring', 'we\'re hiring', 'open position',
    'call for applications', 'phd position', 'phd opening', 'doctoral position', 'fully funded', 'scholarship',
    'alerte emploi', 'offres d\'emploi', 'nouvelles offres', 'offres pour vous', 'votre profil', 'offre de these',
    'sujet de these', 'poste a pourvoir', 'nous recrutons', 'opportunite', 'appel a candidatures',
    'stellenangebote', 'neue jobs', 'passende jobs', 'jobempfehlung', 'wir suchen'
  ]
};

// Senders that are recruiting systems (the company is in the display name) or job boards (alerts).
const ATS = ['greenhouse.io', 'greenhouse-mail.io', 'lever.co', 'hire.lever.co', 'myworkday.com', 'workday.com', 'smartrecruiters.com',
  'teamtailor.com', 'teamtailor-mail.com', 'workablemail.com', 'workable.com', 'ashbyhq.com', 'recruitee.com', 'jobvite.com',
  'icims.com', 'successfactors.com', 'successfactors.eu', 'taleo.net', 'bamboohr.com', 'personio.de', 'personio.com', 'jazzhr.com',
  'breezy.hr', 'pinpointhq.com', 'join.com', 'softgarden.io', 'softgarden.de', 'flatchr.io', 'talent-soft.com', 'cornerstoneondemand.com',
  'oraclecloud.com', 'beetween.com', 'digitalrecruiters.com', 'jobaffinity.fr'];
const BOARDS = ['linkedin.com', 'indeed.com', 'indeedemail.com', 'glassdoor.com', 'welcometothejungle.com', 'wttj.co', 'apec.fr',
  'hellowork.com', 'jobteaser.com', 'francetravail.fr', 'pole-emploi.fr', 'stepstone.de', 'xing.com', 'monster.com', 'jooble.org',
  'academicpositions.com', 'euraxess.ec.europa.eu', 'jobs.ac.uk', 'tanitjobs.com', 'keejob.com', 'wellfound.com', 'ziprecruiter.com',
  'talent.com', 'jobs.ch', 'jobup.ch', 'free-work.com', 'malt.fr', 'abg.asso.fr', 'daad.de', 'campusfrance.org'];
const FREE_MAIL = ['gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'hotmail.fr', 'live.com', 'yahoo.com', 'yahoo.fr', 'icloud.com', 'gmx.de', 'gmx.net', 'web.de', 'orange.fr', 'free.fr', 'laposte.net', 'proton.me', 'protonmail.com'];

const TLD_C = { fr: 'fr', de: 'de', ca: 'ca', tn: 'tn', ch: 'ch' };
const COUNTRY_WORDS = [
  ['fr', /\b(france|paris|lyon|toulouse|marseille|lille|nantes|bordeaux|grenoble|rennes|montpellier|strasbourg|sophia antipolis|saclay)\b/],
  ['de', /\b(germany|deutschland|allemagne|berlin|munich|munchen|hamburg|frankfurt|koln|cologne|stuttgart|dusseldorf|karlsruhe|heidelberg)\b/],
  ['ca', /\b(canada|montreal|toronto|vancouver|ottawa|quebec|calgary|waterloo)\b/],
  ['ch', /\b(switzerland|suisse|schweiz|zurich|geneve|geneva|lausanne|basel|bern|epfl|eth zurich)\b/],
  ['tn', /\b(tunisia|tunisie|tunis|sfax|sousse|ariana|monastir)\b/]
];

const WEAK = ['interview', 'assessment', 'next stage', 'entretien', 'kennenlernen', 'your availability', 'availabilities'];
const hasAny = (t, list) => list.find((p) => t.includes(p)) || '';
const domainOf = (from) => { const m = String(from).match(/@([a-z0-9.-]+)/i); return m ? m[1].toLowerCase() : ''; };
const onDomain = (d, list) => list.some((x) => d === x || d.endsWith('.' + x));
const nameOf = (from) => String(from).replace(/<[^>]*>/, '').replace(/["']/g, '').trim();
const tidy = (s) => String(s || '').replace(/\s+/g, ' ').replace(/^[\s\-–—:|,.]+|[\s\-–—:|,.!]+$/g, '').trim();

// Company: from phrases like "application to Acme", then the sender name (for recruiting systems), then the domain.
function company(subject, body, from, dom) {
  const pats = [
    /\b(?:application|applying|interest)\s+(?:to|at|with|for a (?:role|position) at)\s+([A-Z][\w&.'\- ]{1,40}?)(?=[!.,:;\n]| - | – |\s+(?:for|has|is|was|and)\b|$)/,
    /\b(?:candidature|postuler)\s+(?:chez|a|au sein de|aupres de)\s+([A-Z][\w&.'\- ]{1,40}?)(?=[!.,:;\n]| - | – |\s+(?:pour|a|est)\b|$)/,
    /\b(?:Bewerbung\s+(?:bei|an))\s+(?:der\s+|die\s+)?([A-Z][\w&.'\- ]{1,40}?)(?=[!.,:;\n]| - | – |$)/,
    /\b(?:at|chez|bei)\s+([A-Z][\w&.'\-]{1,30}(?:\s[A-Z][\w&.'\-]{1,20}){0,2})\b/
  ];
  for (const t of [subject, body.slice(0, 600)]) {
    for (const p of pats) { const m = String(t).match(p); if (m && m[1] && !/^(the|our|this|your|la|le|les|notre|votre)$/i.test(m[1].trim())) return tidy(m[1]); }
  }
  const name = nameOf(from)
    .replace(/\b(via|at|@)\s+(workday|greenhouse|lever|smartrecruiters|teamtailor|workable|ashby|recruitee|jobvite|icims|successfactors|taleo|linkedin|indeed)\b.*$/i, '')
    .replace(/\b(careers?|recruiting|recruitment|recrutement|talent( acquisition)?( team)?|hiring( team)?|hr|rh|human resources|people( team)?|jobs?|no-?reply|notifications?|alerts?|team|equipe|karriere|personalabteilung)\b/gi, '')
    .replace(/[|•·]/g, ' ');
  if (tidy(name).length >= 2 && !onDomain(dom, FREE_MAIL) && !onDomain(dom, BOARDS)) return tidy(name);
  if (dom && !onDomain(dom, FREE_MAIL) && !onDomain(dom, ATS) && !onDomain(dom, BOARDS)) {
    const parts = dom.split('.'); const base = parts.length > 2 && parts[parts.length - 2].length <= 3 ? parts[parts.length - 3] : parts[parts.length - 2];
    if (base) return base.charAt(0).toUpperCase() + base.slice(1);
  }
  return tidy(name);
}

function role(subject, body) {
  const pats = [
    /\b(?:position|role|post)\s+(?:of|as)\s+([^,.;:\n]{3,60})/i,
    /\bfor\s+(?:the|our)\s+([^,.;:\n]{3,60}?)\s+(?:position|role|opening|job)\b/i,
    /\bapplication\s+for\s+(?:the\s+)?([^,.;:\n]{3,60}?)(?=\s+(?:at|with|position|role)\b|[,.;:\n]|$)/i,
    /\b(?:au\s+)?poste\s+(?:de|d')\s*([^,.;:\n]{3,60})/i,
    /\bcandidature\s+(?:pour|au poste de|a l'offre)\s+([^,.;:\n]{3,60})/i,
    /\bBewerbung\s+als\s+([^,.;:\n]{3,60})/i,
    /\b(?:admission|programme|program)\s+(?:to|in|for)\s+(?:the\s+)?([^,.;:\n]{3,60})/i
  ];
  for (const t of [subject, body.slice(0, 1500)]) for (const p of pats) { const m = String(t).match(p); if (m) return tidy(m[1].replace(/\s+(?:at|with|in|chez|à|a|au sein de|bei|in der)\s+.*$/i, '')).slice(0, 80); }
  return '';
}

function firstJobLink(body) {
  const links = String(body).match(/https:\/\/[^\s)<>"']{8,300}/g) || [];
  return links.find((u) => /job|career|position|apply|offre|stelle|vacanc|opening|recrut|candidat/i.test(u) && !/unsubscribe|desabonn|abmelden|privacy|preferences/i.test(u)) || '';
}

const SUMMARY = {
  rejected: 'Rejection', offer: 'Offer or admission', interview: 'Interview or test invitation',
  applied: 'Application confirmation', opportunity: 'Opportunity or job alert'
};

// email: { from, subject, text }. Returns the same shape the app expects from Claude.
function classify(email) {
  const from = String(email.from || ''), subject = String(email.subject || ''), body = String(email.text || '');
  const t = norm(subject + ' \n ' + body.slice(0, 4000)), dom = domainOf(from);
  const isBoard = onDomain(dom, BOARDS), isAts = onDomain(dom, ATS);

  let label = '', hit = '';
  for (const k of ['rejected', 'offer', 'interview', 'applied']) { hit = hasAny(t, RULES[k]); if (hit) { label = k; break; } }
  // "leider" or "interview" alone inside a job-board alert is not about the user's own application.
  if (label && isBoard && !isAts && hasAny(t, RULES.opportunity) && !hasAny(norm(subject), RULES[label])) label = '';
  // A plain "thank you for your interest" newsletter is not a confirmation unless an application is mentioned.
  if (label === 'applied' && hit === 'thank you for your interest in' && !/applica|candidat|bewerb/.test(t)) label = '';
  // Generic words ("interview", "entretien" also means maintenance) need an application context and no newsletter signs.
  if (label === 'interview' && WEAK.includes(hit)) {
    const context = /appl(y|ied|ica)|candidat|bewerb|your profile|votre profil|position|poste|role|stelle/.test(t) || RULES.interview.filter((p) => t.includes(p)).length >= 2;
    if (!context || /newsletter|digest|webinar|unsubscribe|desabonn|abmelden/.test(t)) label = '';
  }
  if (!label) { hit = hasAny(t, RULES.opportunity); if (hit || isBoard) label = 'opportunity'; }
  if (!label && isAts) label = 'applied';
  if (!label) return { kind: 'ignore' };

  const tx = norm(subject + ' ' + body.slice(0, 1500));
  const d = /\b(phd|ph\.d|doctora|these|doktorand|promotion)\b/.test(tx) ? 'phd'
    : /\b(master|msc|m\.sc|admission|programme|studiengang|mastere)\b/.test(tx) ? 'master' : 'job';
  const tld = dom.split('.').pop();
  const c = TLD_C[tld] || ((COUNTRY_WORDS.find(([, re]) => re.test(tx)) || [''])[0]);
  const stage = label === 'interview' ? 'interview' : label === 'offer' ? 'offer' : 'applied';
  const result = label === 'rejected' ? 'rejected' : 'open';

  return {
    kind: label === 'opportunity' ? 'opportunity' : 'application',
    org: company(subject, body, from, dom).slice(0, 120), role: role(subject, body), c, d, stage, result,
    summary: SUMMARY[label] + (hit ? ` ("${hit}")` : ''), link: firstJobLink(body)
  };
}

module.exports = { classify, norm };
