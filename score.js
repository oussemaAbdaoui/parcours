/* Parcours match score: how well an offer fits your profile, from 0 to 100, with a breakdown.
   Runs in the browser (window.ParcoursScore) and in Node (module.exports) for tests.

   Components and weights (sum 100):
     skills 35      your CV skills vs the offer's title and text (title counts double)
     seniority 15   offer level (internship, junior, senior, years asked) vs your experience
     languages 10   languages the offer requires vs your levels
     place 10       country preference, remote, visa sponsorship or restrictions
     competition 10 applicant count when known (LinkedIn), otherwise freshness as a proxy
     company 10     company rating from reviews when known
     timing 10      posting freshness and deadline
   A component without data scores neutral (50%) and lowers the confidence figure. */
(function (root) {
  'use strict';

  // Skill dictionary: canonical name -> patterns (EN, FR, DE). Matched on normalised text with word boundaries.
  const SKILLS = {
    'python': ['python'], 'java': ['java(?!script)'], 'javascript': ['javascript', 'js'], 'typescript': ['typescript'],
    'c++': ['c\\+\\+', 'cpp'], 'c#': ['c#', '\\.net', 'dotnet'], 'go': ['golang'], 'rust': ['rust'], 'r': ['r(?= |,|/)'],
    'sql': ['sql', 'postgres(?:ql)?', 'mysql', 'sqlite'], 'nosql': ['nosql', 'mongodb', 'redis', 'cassandra'],
    'machine learning': ['machine learning', 'apprentissage automatique', 'maschinelles lernen', 'ml'],
    'deep learning': ['deep learning', 'apprentissage profond', 'neural networks?', 'reseaux de neurones'],
    'nlp': ['nlp', 'natural language processing', 'traitement automatique (?:du|des) langues?', 'tal', 'text mining'],
    'llm': ['llms?', 'large language models?', 'gpt', 'genai', 'generative ai', 'ia generative', 'rag', 'retrieval.augmented'],
    'computer vision': ['computer vision', 'vision par ordinateur', 'image processing', 'object detection', 'opencv'],
    'reinforcement learning': ['reinforcement learning', 'apprentissage par renforcement'],
    'speech': ['speech recognition', 'asr', 'text.to.speech', 'tts'],
    'pytorch': ['pytorch', 'torch'], 'tensorflow': ['tensorflow', 'keras'], 'jax': ['jax'],
    'hugging face': ['hugging ?face', 'transformers'], 'scikit-learn': ['scikit.learn', 'sklearn'],
    'pandas': ['pandas', 'numpy'], 'spark': ['spark', 'pyspark', 'databricks'], 'langchain': ['langchain', 'llamaindex'],
    'mlops': ['mlops', 'mlflow', 'kubeflow', 'model deployment', 'model serving'],
    'statistics': ['statistics', 'statistiques', 'statistik', 'bayesian', 'probabilit'],
    'data engineering': ['data engineering', 'etl', 'airflow', 'dbt', 'data pipelines?'],
    'backend': ['backend', 'back.end', 'rest api', 'apis? rest', 'microservices?'],
    'fastapi': ['fastapi'], 'django': ['django'], 'flask': ['flask'], 'spring': ['spring(?: boot)?'],
    'node.js': ['node(?:\\.?js)?', 'express(?:\\.js)?', 'nestjs'], 'react': ['react(?:\\.js)?'], 'angular': ['angular'],
    'docker': ['docker', 'containers?'], 'kubernetes': ['kubernetes', 'k8s'], 'linux': ['linux', 'unix', 'bash'],
    'git': ['git', 'github', 'gitlab'], 'ci/cd': ['ci/cd', 'cicd', 'continuous integration', 'jenkins', 'github actions'],
    'aws': ['aws', 'amazon web services', 'sagemaker'], 'gcp': ['gcp', 'google cloud', 'vertex ai'], 'azure': ['azure'],
    'research': ['research', 'recherche', 'forschung', 'publications?', 'papers?'],
  };
  const COMPILED = Object.entries(SKILLS).map(([k, ps]) => [k, new RegExp('(?:^|[^a-z0-9+#])(?:' + ps.join('|') + ')(?=$|[^a-z0-9+#])')]);

  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ');
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const skillsIn = (text) => { const t = ' ' + norm(text) + ' '; return COMPILED.filter(([, re]) => re.test(t)).map(([k]) => k); };

  // Seniority: offer level from wording, 0 = internship .. 4 = lead/principal.
  function offerLevel(t) {
    if (/\b(stage|stagiaire|intern(ship)?|pfe|praktikum|werkstudent|alternance|apprenti)/.test(t)) return { lvl: 0, label: 'internship' };
    const yrs = t.match(/(\d{1,2})\s*\+?\s*(?:years?|yrs|ans|jahre)/);
    const y = yrs ? +yrs[1] : null;
    if (/\b(principal|staff|head of|director|lead|chef de|leiter)\b/.test(t) || (y !== null && y >= 8)) return { lvl: 4, label: 'lead', years: y };
    if (/\b(senior|sr\.?|confirme|experimente|erfahren)\b/.test(t) || (y !== null && y >= 5)) return { lvl: 3, label: 'senior', years: y };
    if (/\b(junior|jr\.?|graduate|debutant|entry.level|jeune diplome|berufseinsteiger|new grad)\b/.test(t) || (y !== null && y <= 2)) return { lvl: 1, label: 'junior', years: y };
    if (y !== null) return { lvl: 2, label: 'mid', years: y };
    return { lvl: null, label: 'not stated' };
  }
  const profileLevel = (years) => (years == null ? 1 : years < 1 ? 1 : years < 3 ? 1.5 : years < 5 ? 2 : years < 8 ? 3 : 4);

  // Languages: what the offer requires, from explicit requirements or the language it is written in.
  const LVL = { '': 0, A1: 1, A2: 2, B1: 3, B2: 4, C1: 5, C2: 6, native: 6 };
  function offerLanguages(t) {
    const need = {};
    if (/\b(fluent|fluency|excellent|very good|courant|bilingue|verhandlungssicher|fliessend|sehr gute)\b[^.]{0,40}\b(german|allemand|deutsch)/.test(t) || /\bdeutschkenntnisse\b/.test(t)) need.de = 4;
    if (/\b(fluent|fluency|courant|bilingue|excellent)\b[^.]{0,40}\b(french|francais)/.test(t) || /\b(francais|french) (courant|obligatoire|required|fluent|native)\b/.test(t)) need.fr = 4;
    if (/\b(fluent|fluency|courant|excellent|professional)\b[^.]{0,40}\b(english|anglais|englisch)/.test(t) || /\b(english|anglais|englisch) (is )?(courant|required|mandatory|fluent|obligatoire|professionnel)\b/.test(t)) need.en = 4;
    if (/\b(deutsch|german|allemand) (fliessend|verhandlungssicher|required|fluent|courant|obligatoire)\b/.test(t)) need.de = 4;
    // Written language as a weaker signal.
    const de = (t.match(/\b(und|der|die|das|mit|fur|wir|sie|ihre)\b/g) || []).length;
    const fr = (t.match(/\b(et|les|des|pour|vous|nous|avec|une)\b/g) || []).length;
    const en = (t.match(/\b(and|the|with|for|you|our|will)\b/g) || []).length;
    const top = Math.max(de, fr, en);
    if (top >= 4) { const w = top === de ? 'de' : top === fr ? 'fr' : 'en'; if (!need[w]) need[w] = 3; }
    return need;
  }

  function daysSince(iso, now) { const t = Date.parse(iso || ''); return isNaN(t) ? null : Math.floor((now - t) / 864e5); }

  const WEIGHTS = { skills: 35, seniority: 15, languages: 10, place: 10, competition: 10, company: 10, timing: 10 };

  /* offer: {title, desc, org, location, c, kind, posted, deadline, type, applicants, company:{rating,count,source}}
     profile: {skills:[...], years, languages:{en,fr,de}, countries:[order], remote:'yes'|'ok'|'no', visa:{fr:true,...}} */
  function score(offer, profile, now = Date.now()) {
    const p = profile || {};
    const title = norm(offer.title), body = norm((offer.title || '') + ' ' + (offer.desc || '') + ' ' + (offer.type || ''));
    const parts = {};

    // 1. Skills
    const mine = new Set(p.skills || []);
    const inTitle = skillsIn(offer.title), inBody = skillsIn(body);
    const wanted = [...new Set([...inTitle, ...inBody])];
    if (!mine.size) parts.skills = { v: 0.5, known: false, note: 'Add your CV to score skills' };
    else if (!wanted.length) parts.skills = { v: 0.5, known: false, note: 'Offer lists no recognisable skills' };
    else {
      const w = (k) => (inTitle.includes(k) ? 2 : 1);
      const total = wanted.reduce((a, k) => a + w(k), 0), got = wanted.filter((k) => mine.has(k));
      const cover = got.reduce((a, k) => a + w(k), 0) / total;
      parts.skills = { v: clamp(0.15 + 0.85 * cover), known: true, note: `${got.length}/${wanted.length} skills: ${got.slice(0, 5).join(', ') || 'none'}`, missing: wanted.filter((k) => !mine.has(k)).slice(0, 5) };
    }

    // 2. Seniority
    const lv = offerLevel(body);
    if (offer.kind === 'phd' || offer.kind === 'master') parts.seniority = { v: (p.years ?? 0) <= 4 ? 1 : 0.7, known: true, note: offer.kind === 'phd' ? 'PhD position' : "Master's programme" };
    else if (lv.lvl === null) parts.seniority = { v: 0.6, known: false, note: 'Level not stated' };
    else {
      const gap = lv.lvl - profileLevel(p.years);
      const v = gap <= -2 ? 0.55 : gap <= 0 ? 1 : gap <= 1 ? 0.6 : gap <= 2 ? 0.25 : 0.05;
      parts.seniority = { v, known: true, note: `Asks ${lv.label}${lv.years != null ? ` (${lv.years}+ yrs)` : ''}` };
    }

    // 3. Languages
    const need = offerLanguages(body), langs = p.languages || {};
    const needs = Object.entries(need);
    if (!needs.length) parts.languages = { v: 0.7, known: false, note: 'No language requirement found' };
    else {
      const worst = Math.min(...needs.map(([l, req]) => clamp((LVL[langs[l] || ''] || 0) / req)));
      const names = { en: 'English', fr: 'French', de: 'German' };
      parts.languages = { v: worst, known: true, note: needs.map(([l]) => names[l] + (langs[l] ? ` (you: ${langs[l]})` : ' (not in profile)')).join(', ') };
    }

    // 4. Place: preference order, remote, visa
    const order = p.countries || [], rank = order.indexOf(offer.c);
    let place = rank < 0 ? (offer.c === 'gl' ? 0.6 : 0.4) : 1 - rank * (0.5 / Math.max(1, order.length - 1));
    const remote = /\b(remote|teletravail|full remote|homeoffice|home office|anywhere)\b/.test(body);
    if (remote && p.remote !== 'no') place = Math.min(1, place + 0.15);
    if (!remote && p.remote === 'yes') place -= 0.2;
    const needVisa = p.visa && p.visa[offer.c];
    let visaNote = '';
    if (needVisa) {
      if (/\b(visa (sponsor|support|assistance)|sponsorship|relocation|we sponsor|aide a la relocalisation|visum)\b/.test(body)) { place = Math.min(1, place + 0.2); visaNote = ', visa or relocation offered'; }
      else if (/\b(eu citizens?|eu passport|right to work|work permit required|must be authori[sz]ed|nationalite (francaise|europeenne)|citoyen europeen)\b/.test(body)) { place -= 0.45; visaNote = ', work permit restriction'; }
    }
    parts.place = { v: clamp(place), known: true, note: (rank >= 0 ? `Country #${rank + 1} for you` : 'Country not in your list') + (remote ? ', remote possible' : '') + visaNote };

    // 5. Competition
    const age = daysSince(offer.posted, now) ?? daysSince(offer.foundAt ? new Date(offer.foundAt).toISOString() : '', now);
    if (typeof offer.applicants === 'number') {
      const a = offer.applicants;
      parts.competition = { v: a < 10 ? 1 : a < 25 ? 0.85 : a < 50 ? 0.7 : a < 100 ? 0.5 : a < 200 ? 0.3 : 0.15, known: true, note: `${a}${offer.applicantsCapped ? '+' : ''} applicants` };
    } else if (age != null) parts.competition = { v: age <= 2 ? 0.9 : age <= 7 ? 0.7 : age <= 14 ? 0.5 : 0.3, known: false, note: `Applicants unknown, posted ${age} d ago` };
    else parts.competition = { v: 0.5, known: false, note: 'Applicants unknown' };

    // 6. Company reviews
    const co = offer.company;
    if (co && typeof co.rating === 'number') {
      const trust = clamp((co.count || 0) / 30);            // few reviews pull the rating toward neutral
      const r = clamp((co.rating - 2.5) / 2);               // 2.5 -> 0, 4.5 -> 1
      parts.company = { v: 0.5 + (r - 0.5) * trust, known: true, note: `${co.rating.toFixed(1)}/5 from ${co.count || '?'} reviews (${co.source})` };
    } else parts.company = { v: 0.5, known: false, note: 'No company reviews found' };

    // 7. Timing
    const left = offer.deadline ? -daysSince(offer.deadline, now) : null;
    if (left != null && left < 0) parts.timing = { v: 0, known: true, note: 'Deadline passed' };
    else if (left != null) parts.timing = { v: left <= 3 ? 0.7 : 1, known: true, note: left <= 7 ? `Deadline in ${left} d, apply soon` : `Deadline in ${left} d` };
    else if (age != null) parts.timing = { v: age <= 7 ? 1 : age <= 21 ? 0.7 : 0.4, known: true, note: `Posted ${age} d ago` };
    else parts.timing = { v: 0.6, known: false, note: 'Date unknown' };

    let total = 0, knownW = 0;
    for (const [k, w] of Object.entries(WEIGHTS)) { total += w * parts[k].v; if (parts[k].known) knownW += w; }
    // Dealbreakers cap the score whatever the rest says.
    const blockers = [];
    if (parts.languages.known && parts.languages.v < 0.5) blockers.push('Required language missing');
    if (visaNote === ', work permit restriction') blockers.push('Work permit restriction');
    if (parts.timing.v === 0) blockers.push('Deadline passed');
    if (blockers.length) total = Math.min(total, 40);
    const urgent = left != null && left >= 0 && left <= 7;
    return { score: Math.round(total), confidence: knownW / 100, parts, urgent, blockers };
  }

  // Profile helpers
  function profileFromCv(text) {
    const t = norm(text);
    const years = (() => { const m = t.match(/(\d{1,2})\s*\+?\s*(?:years?|ans|jahre)\s+(?:of\s+)?(?:experience|d.experience|erfahrung)/); return m ? +m[1] : null; })();
    return { skills: skillsIn(text), years };
  }

  const api = { score, skillsIn, profileFromCv, offerLevel, WEIGHTS, SKILL_NAMES: Object.keys(SKILLS) };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.ParcoursScore = api;
})(typeof window !== 'undefined' ? window : globalThis);
