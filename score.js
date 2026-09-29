/* Parcours match score and CV parser. Browser: window.ParcoursScore. Node: module.exports (tests).

   Score, 0-100, from nine signals (weights sum to 100):
     skills 28       your skills vs the offer; required skills weigh more than nice-to-haves, title mentions most,
                     and a related skill in the same family (PyTorch for TensorFlow) earns half credit
     role 10         offer title vs the roles and fields in your CV and saved searches
     seniority 12    level asked (internship, junior, senior, years) vs your experience
     education 6     degree asked (PhD, master's, engineer, bachelor) vs yours
     languages 10    languages required vs your levels
     place 10        country order, remote, visa sponsorship or work-permit restrictions
     competition 8   applicant count (LinkedIn), otherwise freshness
     company 8       company rating, weighted by review count
     timing 8        freshness and deadline
   Missing data scores neutral and lowers the confidence figure. Dealbreakers cap the score at 40. */
(function (root) {
  'use strict';

  // name -> [family, patterns]. Patterns are regex fragments matched on accent-stripped lowercase text.
  const SKILLS = {
    // languages
    'python': ['lang', ['python']], 'java': ['lang', ['java(?!script)']], 'javascript': ['lang', ['javascript', 'js', 'ecmascript']],
    'typescript': ['lang', ['typescript', 'ts']], 'c++': ['lang', ['c\\+\\+', 'cpp']], 'c': ['lang', ['c(?= ?(?:,|/|and|et|programming|language))']],
    'c#': ['lang', ['c#', '\\.net', 'dotnet', 'asp\\.net']], 'go': ['lang', ['golang', 'go(?= ?(?:,|/|lang))']], 'rust': ['lang', ['rust']],
    'php': ['lang', ['php']], 'kotlin': ['lang', ['kotlin']], 'swift': ['lang', ['swift']], 'scala': ['lang', ['scala']],
    'r': ['lang', ['r(?= ?(?:,|/|studio|programming|language))', 'rstudio']], 'matlab': ['lang', ['matlab']], 'bash': ['lang', ['bash', 'shell scripting']],
    'sql': ['db', ['sql', 't-sql', 'pl/sql']],
    // AI / ML
    'machine learning': ['ml', ['machine learning', 'apprentissage automatique', 'maschinelles lernen', 'ml']],
    'deep learning': ['ml', ['deep learning', 'apprentissage profond', 'neural networks?', 'reseaux de neurones', 'dnn']],
    'statistics': ['ml', ['statistics', 'statistiques', 'statistik', 'bayesian', 'probabilit\\w*', 'hypothesis testing']],
    'xgboost': ['ml', ['xgboost', 'lightgbm', 'catboost', 'gradient boosting']],
    'time series': ['ml', ['time.series', 'series temporelles', 'forecasting', 'prevision']],
    'lstm': ['ml', ['lstm', 'rnn', 'gru', 'recurrent neural']],
    'cnn': ['cv', ['cnn', 'convolutional']],
    'reinforcement learning': ['ml', ['reinforcement learning', 'apprentissage par renforcement', 'rl(?= |,)']],
    'recommender systems': ['ml', ['recommender systems?', 'recommendation systems?', 'systemes de recommandation']],
    'anomaly detection': ['ml', ['anomaly detection', 'intrusion detection', 'fraud detection', 'detection d.anomalies']],
    'explainable ai': ['xai', ['xai', 'explainab\\w+', 'interpretab\\w+', 'explicab\\w+', 'shap', 'lime']],
    'nlp': ['nlp', ['nlp', 'natural language processing', 'traitement automatique (?:du|des) langues?', 'tal', 'text mining', 'text classification', 'named entity', 'ner', 'sentiment analysis']],
    'llm': ['llm', ['llms?', 'large language models?', 'gpt(?:-?4o?)?', 'genai', 'generative ai', 'ia generative', 'fine.tun\\w+', 'prompt engineering', 'instruction tuning', 'lora', 'qlora', 'peft']],
    'rag': ['llm', ['rag', 'retrieval.augmented', 'graphrag', 'semantic search', 'recherche semantique']],
    'agents': ['llm', ['ai agents?', 'agentic', 'langgraph', 'autogen', 'crewai', 'multi.agent', 'tool calling', 'function calling']],
    'information retrieval': ['ir', ['information retrieval', 'bm25', 'dense retrieval', 'hybrid search', 'rerank\\w*', 'ranking models?', 'search engines?']],
    'embeddings': ['ir', ['embeddings?', 'sentence.transformers', 'bge(?:-m3)?', 'e5', 'word2vec']],
    'vector databases': ['ir', ['vector (?:databases?|stores?|db)', 'faiss', 'chroma(?:db)?', 'pinecone', 'weaviate', 'qdrant', 'milvus', 'pgvector']],
    'llm evaluation': ['llm', ['llm evaluation', 'g.eval', 'ragas', 'hallucination', 'evaluation of llms?']],
    'computer vision': ['cv', ['computer vision', 'vision par ordinateur', 'image processing', 'object detection', 'segmentation', 'opencv', 'yolo']],
    'ocr': ['cv', ['ocr', 'optical character recognition', 'document ai', 'document understanding']],
    'vision-language': ['cv', ['vision.language', 'vlms?', 'multimodal', 'multi.modal', 'clip']],
    'speech': ['ml', ['speech recognition', 'asr', 'text.to.speech', 'tts', 'whisper']],
    'pytorch': ['dlfw', ['pytorch', 'torch']], 'tensorflow': ['dlfw', ['tensorflow', 'keras']], 'jax': ['dlfw', ['jax']],
    'hugging face': ['llmfw', ['hugging ?face', 'transformers']], 'langchain': ['llmfw', ['langchain', 'llamaindex', 'llama.index']],
    'ollama': ['llmfw', ['ollama', 'vllm', 'llama\\.cpp']],
    'scikit-learn': ['mllib', ['scikit.learn', 'sklearn']], 'pandas': ['mllib', ['pandas', 'numpy', 'polars']],
    'spark': ['data', ['spark', 'pyspark', 'databricks', 'hadoop']], 'data engineering': ['data', ['data engineering', 'etl', 'elt', 'airflow', 'dbt', 'data pipelines?', 'kafka']],
    'mlops': ['mlops', ['mlops', 'mlflow', 'kubeflow', 'model deployment', 'model serving', 'model monitoring', 'weights ?& ?biases', 'wandb', 'dvc']],
    // optimization, research
    'optimization': ['opt', ['optimi[sz]ation', 'operations research', 'recherche operationnelle', 'or-tools', 'linear programming', 'milp', 'gurobi', 'cplex']],
    'constraint programming': ['opt', ['constraint programming', 'cp-sat', 'sat solvers?', 'smt', 'z3', 'minizinc', 'programmation par contraintes']],
    'monte carlo': ['opt', ['monte.carlo', 'simulation']],
    'research': ['research', ['research', 'recherche', 'forschung', 'publications?', 'papers?', 'peer.reviewed', 'acm', 'ieee', 'conference']],
    // backend, web
    'backend': ['backend', ['backend', 'back.end', 'microservices?', 'distributed systems']],
    'rest api': ['api', ['rest(?:ful)?(?: api)?', 'apis? rest', 'openapi', 'swagger']], 'graphql': ['api', ['graphql']], 'grpc': ['api', ['grpc', 'protobuf']],
    'soap': ['api', ['soap']], 'fastapi': ['pyweb', ['fastapi']], 'django': ['pyweb', ['django']], 'flask': ['pyweb', ['flask']],
    'spring': ['jvmweb', ['spring(?: boot)?']], 'node.js': ['jsweb', ['node(?:\\.?js)?', 'express(?:\\.js)?']], 'nestjs': ['jsweb', ['nest(?:\\.?js)']],
    'laravel': ['phpweb', ['laravel', 'symfony']], 'react': ['front', ['react(?:\\.js)?', 'next\\.?js']], 'vue': ['front', ['vue(?:\\.?js)?', 'nuxt']],
    'angular': ['front', ['angular']], 'html/css': ['front', ['html5?', 'css3?', 'tailwind', 'sass']], 'flutter': ['mobile', ['flutter', 'dart']],
    'android': ['mobile', ['android']], 'ios': ['mobile', ['ios(?= |,)', 'swiftui']],
    // data stores
    'postgresql': ['db', ['postgres(?:ql)?']], 'mysql': ['db', ['mysql', 'mariadb']], 'mongodb': ['nosql', ['mongo(?:db)?']],
    'redis': ['nosql', ['redis']], 'elasticsearch': ['nosql', ['elastic(?:search)?', 'opensearch']], 'neo4j': ['nosql', ['neo4j', 'graph databases?', 'knowledge graphs?']],
    // devops, cloud, quality
    'docker': ['devops', ['docker', 'containers?', 'podman']], 'kubernetes': ['devops', ['kubernetes', 'k8s', 'helm']],
    'ci/cd': ['devops', ['ci/cd', 'cicd', 'continuous integration', 'jenkins', 'github actions', 'gitlab ci']],
    'terraform': ['devops', ['terraform', 'ansible', 'infrastructure as code']], 'linux': ['devops', ['linux', 'unix']],
    'git': ['tools', ['git', 'github', 'gitlab', 'bitbucket']], 'monitoring': ['devops', ['monitoring', 'observability', 'grafana', 'prometheus']],
    'aws': ['cloud', ['aws', 'amazon web services', 'sagemaker', 'ec2', 's3']], 'gcp': ['cloud', ['gcp', 'google cloud', 'vertex ai']], 'azure': ['cloud', ['azure']],
    'testing': ['quality', ['unit tests?', 'pytest', 'junit', 'tdd', 'load testing', 'locust', 'jmeter', 'tests? automatises']],
    'security': ['sec', ['cybersecurity', 'cyber.security', 'securite', 'tls', 'owasp', 'penetration testing', 'network security']],
    'iot': ['embedded', ['iot', 'raspberry pi', 'arduino', 'embedded systems?', 'systemes embarques']],
    'agile': ['method', ['agile', 'scrum', 'kanban', 'jira']],
  };
  const COMPILED = Object.entries(SKILLS).map(([k, [fam, ps]]) =>
    [k, fam, new RegExp('(?:^|[^a-z0-9+#])(?:' + ps.join('|') + ')(?=$|[^a-z0-9+#])')]);
  const FAMILY = Object.fromEntries(Object.entries(SKILLS).map(([k, [f]]) => [k, f]));

  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[\u2013\u2014]/g, '-').replace(/\s+/g, ' ');
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const skillsIn = (text) => { const t = ' ' + norm(text) + ' '; return COMPILED.filter(([, , re]) => re.test(t)).map(([k]) => k); };
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const termIn = (term, t) => new RegExp('(?:^|[^a-z0-9+#])' + escRe(norm(term)) + '(?=$|[^a-z0-9+#])').test(t);

  /* ---------- CV parser ---------- */
  const HEADINGS = {
    experience: ['professional experience', 'work experience', 'experience professionnelle', 'experiences professionnelles', 'experiences', 'experience', 'employment', 'berufserfahrung', 'research experience', 'research', 'internships?', 'stages'],
    education: ['education', 'formation', 'formations', 'academic background', 'ausbildung', 'studium'],
    skills: ['technical skills', 'skills', 'competences techniques', 'competences', 'kenntnisse', 'tools', 'technologies'],
    projects: ['projects', 'projets', 'personal projects', 'academic projects', 'projekte'],
    languages: ['languages', 'langues', 'sprachen'],
    certifications: ['certifications', 'certificates', 'certificats', 'awards', 'honors'],
    publications: ['publications', 'papers'],
    summary: ['summary', 'profile', 'profil', 'about me', 'objective'],
  };
  // Finds section headings even when the CV text has no line breaks (PDF extraction): headings are Title Case or CAPS words.
  function sections(raw) {
    const found = [];
    for (const [sec, words] of Object.entries(HEADINGS)) {
      for (const w of words) {
        const re = new RegExp('(?:^|[\\s•|·:])(' + w.split(' ').map((x) => '(?:' + x[0].toUpperCase() + x.slice(1) + '|' + x.toUpperCase() + ')').join('\\s+') + ')(?=[\\s:•|·])', 'g');
        let m;
        const txt = raw.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        while ((m = re.exec(txt))) found.push({ sec, at: m.index + m[0].indexOf(m[1]), len: m[1].length });
      }
    }
    found.sort((a, b) => a.at - b.at);
    const keep = found.filter((f, i) => !found.some((g, j) => j !== i && g.at <= f.at && g.at + g.len >= f.at + f.len && g.len > f.len));
    const out = {};
    keep.forEach((f, i) => {
      const end = i + 1 < keep.length ? keep[i + 1].at : raw.length;
      if (end - f.at > 25) out[f.sec] = (out[f.sec] || '') + ' ' + raw.slice(f.at + f.len, end);
    });
    return out;
  }
  const MONTH = { jan: 1, janv: 1, feb: 2, fev: 2, fevr: 2, mar: 3, mars: 3, apr: 4, avr: 4, may: 5, mai: 5, jun: 6, juin: 6, jul: 7, juil: 7,
    aug: 8, aout: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12 };
  // Date ranges like "Jun 2025 - Jan 2026", "02/2024 - 08/2024", "2023 - present". Returns months.
  function rangesIn(text, now) {
    const t = norm(text), out = [];
    const d = '(?:(jan|janv|feb|fev|fevr|mar|mars|apr|avr|may|mai|jun|juin|jul|juil|aug|aout|sep|sept|oct|nov|dec)[a-z]*\\.?\\s+|(\\d{1,2})/)?((?:19|20)\\d{2})';
    const re = new RegExp(d + '\\s*(?:-|to|a|au|bis)\\s*(?:' + d + '|(present|current|now|ongoing|aujourd.hui|actuel|heute|en cours))', 'g');
    let m;
    const cur = new Date(now);
    while ((m = re.exec(t))) {
      const sm = m[1] ? MONTH[m[1]] : m[2] ? +m[2] : 1, sy = +m[3];
      let em, ey;
      if (m[7]) { em = cur.getMonth() + 1; ey = cur.getFullYear(); }
      else { em = m[4] ? MONTH[m[4]] : m[5] ? +m[5] : 12; ey = +m[6]; }
      const months = (ey - sy) * 12 + (em - sm) + 1;
      if (months > 0 && months < 600) out.push({ months, at: m.index, text: m[0], hasMonth: !!(m[1] || m[2]) });
    }
    return out;
  }
  const LEVEL_WORDS = [[/native|maternelle|langue maternelle|muttersprache|bilingual|bilingue/, 'native'], [/\bc2\b|proficient|courant|fluent|fliessend|verhandlungssicher/, 'C1'],
    [/\bc1\b|advanced|avance|professional working|professionnel/, 'C1'], [/\bb2\b|upper.intermediate|intermediaire avance|gute kenntnisse/, 'B2'],
    [/\bb1\b|intermediate|intermediaire|conversational/, 'B1'], [/\ba2\b|elementary|basic|notions|grundkenntnisse/, 'A2'], [/\ba1\b|beginner|debutant/, 'A1']];
  const LANGS = { en: 'english|anglais|englisch', fr: 'french|francais|franzosisch', de: 'german|allemand|deutsch', ar: 'arabic|arabe|arabisch', es: 'spanish|espagnol|spanisch', it: 'italian|italien|italienisch' };
  function languagesIn(text) {
    const t = norm(text), out = {};
    for (const [code, names] of Object.entries(LANGS)) {
      const m = t.match(new RegExp('\\b(?:' + names + ')\\b\\s*[(:\\-,]?\\s*([^,;|·•)]{0,28})'));
      if (!m) continue;
      const lvl = (m[1].match(/\b(a1|a2|b1|b2|c1|c2)\b/) || [])[1];
      out[code] = lvl ? lvl.toUpperCase() : ((LEVEL_WORDS.find(([re]) => re.test(m[1])) || [])[1] || 'B1');
    }
    const toeic = t.match(/toeic\D{0,10}(\d{3})/); if (toeic) out.en = +toeic[1] >= 945 ? 'C1' : +toeic[1] >= 785 ? 'B2' : 'B1';
    const ielts = t.match(/ielts\D{0,10}(\d(?:\.\d)?)/); if (ielts) out.en = +ielts[1] >= 7 ? 'C1' : +ielts[1] >= 5.5 ? 'B2' : 'B1';
    const delf = t.match(/\b(delf|dalf)\s*(a1|a2|b1|b2|c1|c2)/); if (delf) out.fr = delf[2].toUpperCase();
    return out;
  }
  const DEGREE = [[4, /\b(ph\.?\s?d|doctorat|doctorate|doktor)\b/], [3, /\b(engineering degree|engineer(?:ing)? diploma|diplome d.ingenieur|cycle ingenieur|master|msc|m\.sc|mastere|bac\s*\+\s*5)\b/],
    [2, /\b(bachelor|licence|bsc|b\.sc|bac\s*\+\s*3)\b/], [1, /\b(bts|dut|associate|bac\s*\+\s*2|classes? preparatoires?|preparatory)\b/]];
  const DEGREE_NAME = { 4: 'PhD', 3: "Master's or engineer", 2: "Bachelor's", 1: 'Two-year degree' };
  const ROLE_WORDS = '(?:engineer|developer|developpeur|ingenieur|scientist|researcher|chercheur|analyst|intern|stagiaire|architect|consultant|assistant|lead)';
  const STOP = new Set(('the and for with from into that this our your their using used use based data model models system systems team teams work working project projects research ' +
    'university universite school ecole lab laboratory company paper papers final year thesis intern internship present january february march april may june july august september october ' +
    'november december english french arabic german native skills languages education experience professional certifications tunisia france paris sfax sousse monastir bizerte tunis ' +
    'api apis cv linkedin github gmail com pdf poc ile-de-france umr cnrs inria enit enis insat enicarthage ipein ipeim ipest esprit ensi supcom ' +
    'ceo cto hr rh usa uk eu tbd etc lipn enib ras chi ieee acm').split(' '));
  // Tech-looking terms not in the dictionary (mixed case, digits, dots, dashes): kept so offers can match them literally.
  function extraTerms(text, known) {
    // Drop emails, links and phone numbers first: they look technical but are not skills.
    const t = String(text || '').replace(/\S+@\S+/g, ' ').replace(/(?:https?:\/\/)?(?:www\.)?[\w-]+\.(?:com|org|net|io|fr|tn|dev|me)\S*/gi, ' ').replace(/\+?\d[\d\s().-]{7,}/g, ' ');
    const cands = t.match(/[A-Za-z][A-Za-z0-9]*(?:[.+#-][A-Za-z0-9+#]+)*/g) || [];
    const seen = new Map();
    for (const c of cands) {
      const n = norm(c).replace(/\.$/, '');
      if (n.length < 3 || n.length > 24 || STOP.has(n) || /^\d/.test(n)) continue;
      // Technical-looking in its original form: an inner capital (PyTorch, BGE-M3), a digit, or a symbol with a capital.
      // Lowercase hyphenated words ("real-time", "black-box") are ordinary English.
      const techy = /[a-z][A-Z]|[A-Z]{2,}/.test(c) || (/\d/.test(c) && /[A-Za-z]{2}/.test(c)) || (/[.+#]/.test(c.replace(/\.$/, '')) && /[A-Z]/.test(c));
      if (!techy || /^[A-Z][a-z]+(?:-[a-z]+)+$/.test(c)) continue;
      if (skillsIn(c).length) continue;
      seen.set(n, (seen.get(n) || 0) + 1);
    }
    return [...seen.keys()].filter((k) => !known.includes(k)).slice(0, 40);
  }
  function parseCv(text, now = Date.now()) {
    const raw = String(text || '');
    const secs = sections(raw);
    const skills = skillsIn(raw);
    // Experience: date ranges outside Education; internships and research stays count half.
    const workText = (secs.experience || '') + ' ' + (secs.projects ? '' : '');
    const eduText = norm(secs.education || '');
    const ranges = rangesIn(workText.trim() ? workText : raw, now).filter((r) => !eduText.includes(norm(r.text)) && r.hasMonth);
    let months = 0;
    for (const r of ranges) {
      const around = norm((workText || raw).slice(Math.max(0, r.at - 160), r.at + 160));
      months += /\b(intern|internship|stage|stagiaire|pfe|final.year|werkstudent|praktikum|apprenti|alternance)\b/.test(around) ? r.months / 2 : r.months;
    }
    const years = ranges.length ? Math.round(months / 6) / 2 : null;
    // Education
    const eduSrc = norm(secs.education || raw);
    const deg = DEGREE.find(([, re]) => re.test(eduSrc)) || [0];
    const gradYear = (() => { const ys = (eduSrc.match(/\b(19|20)\d{2}\b/g) || []).map(Number); return ys.length ? Math.max(...ys) : null; })();
    const field = ((eduSrc.match(/(?:engineering degree|diplome d.ingenieur|master|bachelor|licence)[^a-z]{0,5}(?:in |en |of )?([a-z &]{4,60})/) || [])[1] || '').trim();
    // Roles from work sections
    const roles = [...new Set(((norm(secs.experience || raw)).match(new RegExp("\\b(?:[a-z+/.-]+\\s){0,3}" + ROLE_WORDS + "\\b", 'g')) || [])
      .map((r) => r.replace(/^((and|et|as|en|a|an|the|le|la|at|chez|de|then|puis|now|also|while|during|pendant|comme)\s+)+/, '').trim()).filter((r) => r.split(' ').length >= 2))].slice(0, 8);
    return {
      skills, extra: extraTerms(raw, skills), years, languages: languagesIn(secs.languages || raw),
      degree: { level: deg[0], name: DEGREE_NAME[deg[0]] || '', field, year: gradYear }, roles,
      sectionsFound: Object.keys(secs),
    };
  }

  /* ---------- offer analysis ---------- */
  function offerLevel(t) {
    if (/\b(stage|stagiaire|intern(ship)?|pfe|praktikum|werkstudent|alternance|apprenti)/.test(t)) return { lvl: 0, label: 'internship' };
    const yrs = t.match(/(\d{1,2})\s*\+?\s*(?:years?|yrs|ans|jahre)/);
    const y = yrs ? +yrs[1] : null;
    if (/\b(principal|staff|head of|director|chef de|leiter)\b/.test(t) || /\blead\b(?! to)/.test(t) || (y !== null && y >= 8)) return { lvl: 4, label: 'lead', years: y };
    if (/\b(senior|sr\.?|confirme|experimente|erfahren)\b/.test(t) || (y !== null && y >= 5)) return { lvl: 3, label: 'senior', years: y };
    if (/\b(junior|jr\.?|graduate|debutant|entry.level|jeune diplome|berufseinsteiger|new grad)\b/.test(t) || (y !== null && y <= 2)) return { lvl: 1, label: 'junior', years: y };
    if (y !== null) return { lvl: 2, label: 'mid', years: y };
    return { lvl: null, label: 'not stated' };
  }
  const profileLevel = (years) => (years == null ? 1 : years < 1 ? 1 : years < 3 ? 1.5 : years < 5 ? 2 : years < 8 ? 3 : 4);
  const LVL = { '': 0, A1: 1, A2: 2, B1: 3, B2: 4, C1: 5, C2: 6, native: 6 };
  function offerLanguages(t) {
    const need = {};
    const strong = '(?:fluent|fluency|excellent|very good|courant|bilingue|verhandlungssicher|fliessend|sehr gute|native|professional)';
    const spec = { de: 'german|allemand|deutsch', fr: 'french|francais|franzosisch', en: 'english|anglais|englisch' };
    for (const [k, n] of Object.entries(spec)) {
      if (new RegExp('\\b' + strong + '\\b[^.]{0,40}\\b(' + n + ')').test(t) || new RegExp('\\b(' + n + ')\\b\\s*(?:is\\s)?(?:courant|required|mandatory|fluent|obligatoire|native|professionnel|c1|c2)').test(t)) need[k] = 4;
    }
    if (/\bdeutschkenntnisse\b/.test(t)) need.de = 4;
    const de = (t.match(/\b(und|der|die|das|mit|fur|wir|sie|ihre)\b/g) || []).length;
    const fr = (t.match(/\b(et|les|des|pour|vous|nous|avec|une)\b/g) || []).length;
    const en = (t.match(/\b(and|the|with|for|you|our|will)\b/g) || []).length;
    const top = Math.max(de, fr, en);
    if (top >= 4) { const w = top === de ? 'de' : top === fr ? 'fr' : 'en'; if (!need[w]) need[w] = 3; }
    return need;
  }
  // Splits the offer into required and nice-to-have parts by the usual phrases.
  function requirementParts(t) {
    const nice = /(nice to have|would be a plus|is a plus|are a plus|bonus|preferred|souhaite|souhaitable|serait un plus|un plus|idealement|apprecie|wunschenswert|von vorteil)/;
    const req = /(required|requirements|must have|you have|you bring|what we.re looking for|qualifications|profil recherche|votre profil|requis|exige|obligatoire|indispensable|anforderungen|ihr profil|was du mitbringst)/;
    const sentences = t.split(/(?<=[.;!?•\n])\s+|\s[-*·•]\s/);
    let reqText = '', niceText = '';
    for (const s of sentences) { if (nice.test(s)) niceText += ' ' + s; else if (req.test(s)) reqText += ' ' + s; }
    return { reqText, niceText };
  }
  function offerDegree(t) {
    if (/\b(ph\.?d|doctorate|doctorat)\b[^.]{0,30}\b(required|requis|mandatory|obligatoire|holder|titulaire)|\b(completed|hold|holding) a ph\.?d/.test(t)) return 4;
    if (/\b(master.?s?|msc|m\.sc|bac\s*\+\s*5|engineering degree|diplome d.ingenieur|ecole d.ingenieurs?)\b/.test(t)) return 3;
    if (/\b(bachelor.?s?|licence|bac\s*\+\s*3|bsc)\b/.test(t)) return 2;
    return 0;
  }
  function daysSince(iso, now) { const t = Date.parse(iso || ''); return isNaN(t) ? null : Math.floor((now - t) / 864e5); }

  // Families where knowing one member says little about another (Python does not make you a Java developer).
  const NO_PARTIAL = new Set(['lang', 'research', 'method', 'tools', 'mobile', 'sec', 'embedded']);
  const WEIGHTS = { skills: 28, role: 10, seniority: 12, education: 6, languages: 10, place: 10, competition: 8, company: 8, timing: 8 };
  const ROLE_GENERIC = new Set(['engineer', 'ingenieur', 'developer', 'developpeur', 'h/f', 'f/h', 'm/w/d', 'intern', 'stage', 'senior', 'junior', 'and', 'et', 'de', 'en', 'in', 'of', 'the', 'for', 'a', 'position', 'poste']);

  function score(offer, profile, now = Date.now()) {
    const p = profile || {};
    const tRaw = (offer.title || '') + ' . ' + (offer.desc || '') + ' . ' + (offer.type || '');
    const body = norm(tRaw), title = norm(offer.title);
    const parts = {};

    // 1. Skills: weighted coverage with required, nice-to-have and related-skill credit
    const mine = new Set(p.skills || []), extra = (p.extra || []).map(norm);
    const myFamilies = new Set([...mine].map((k) => FAMILY[k]));
    const inTitle = new Set(skillsIn(offer.title)), { reqText, niceText } = requirementParts(body);
    const inReq = new Set(skillsIn(reqText)), inNice = new Set(skillsIn(niceText));
    const wanted = [...new Set([...inTitle, ...skillsIn(body)])];
    const extraHits = extra.filter((e) => termIn(e, body));
    if (!mine.size && !extra.length) parts.skills = { v: 0.5, known: false, note: 'Add your CV to score skills' };
    else if (!wanted.length && !extraHits.length) parts.skills = { v: 0.5, known: false, note: 'Offer lists no recognisable skills' };
    else {
      let total = 0, got = 0;
      const have = [], related = [], missing = [];
      for (const k of wanted) {
        const w = inTitle.has(k) ? 2.5 : inReq.has(k) ? 1.6 : inNice.has(k) ? 0.5 : 1;
        total += w;
        if (mine.has(k)) { got += w; have.push(k); }
        else if (myFamilies.has(FAMILY[k]) && !NO_PARTIAL.has(FAMILY[k])) { got += w * 0.5; related.push(k); }
        else missing.push({ k, w });
      }
      // Rare terms from your CV that the offer names literally are strong evidence.
      got += extraHits.length * 1.5; total += extraHits.length * 1.5;
      const cover = total ? got / total : 0;
      missing.sort((a, b) => b.w - a.w);
      parts.skills = {
        v: clamp(0.1 + 0.9 * cover), known: true,
        note: `${have.length + extraHits.length} of ${wanted.length + extraHits.length} matched: ${[...have, ...extraHits].slice(0, 6).join(', ') || 'none'}${related.length ? ` · related: ${related.slice(0, 3).join(', ')}` : ''}`,
        missing: missing.slice(0, 5).map((m) => m.k + (inReq.has(m.k) || inTitle.has(m.k) ? ' (required)' : '')),
      };
    }

    // 2. Role fit: offer title vs your roles, fields and searches
    const roleWords = new Set();
    [...(p.roles || []), ...(p.targets || [])].forEach((r) => norm(r).split(/[^a-z0-9+#]+/).forEach((w) => { if (w.length > 1 && !ROLE_GENERIC.has(w)) roleWords.add(w); }));
    const titleSkills = [...inTitle];
    if (!roleWords.size && !mine.size) parts.role = { v: 0.5, known: false, note: 'No roles in profile' };
    else {
      const tw = title.split(/[^a-z0-9+#]+/).filter((w) => w.length > 1 && !ROLE_GENERIC.has(w));
      const hitW = tw.filter((w) => roleWords.has(w));
      const hitS = titleSkills.filter((k) => mine.has(k));
      const v = tw.length ? clamp((hitW.length + hitS.length * 1.2) / Math.min(3, tw.length)) : 0.5;
      parts.role = { v: clamp(0.15 + 0.85 * v), known: tw.length > 0, note: hitW.length || hitS.length ? `Title matches: ${[...new Set([...hitW, ...hitS])].slice(0, 4).join(', ')}` : 'Title outside your roles and fields' };
    }

    // 3. Seniority
    const lv = offerLevel(body);
    if (offer.kind === 'phd' || offer.kind === 'master') parts.seniority = { v: (p.years ?? 0) <= 4 ? 1 : 0.7, known: true, note: offer.kind === 'phd' ? 'PhD position' : "Master's programme" };
    else if (lv.lvl === null) parts.seniority = { v: 0.6, known: false, note: 'Level not stated' };
    else {
      const gap = lv.lvl - profileLevel(p.years);
      const v = gap <= -2 ? 0.55 : gap <= 0 ? 1 : gap <= 1 ? 0.6 : gap <= 2 ? 0.25 : 0.05;
      parts.seniority = { v, known: true, note: `Asks ${lv.label}${lv.years != null ? ` (${lv.years}+ yrs)` : ''}, you have ${p.years ?? 0} yrs` };
    }

    // 4. Education
    const need = offer.kind === 'phd' ? 3 : offerDegree(body), mineD = (p.degree && p.degree.level) || 0;
    if (!need) parts.education = { v: 0.7, known: false, note: 'No degree stated' };
    else if (!mineD) parts.education = { v: 0.5, known: false, note: `Asks ${DEGREE_NAME[need]}, add your degree in Profile` };
    else parts.education = { v: mineD >= need ? 1 : mineD === need - 1 ? 0.45 : 0.1, known: true, note: `Asks ${DEGREE_NAME[need]}, you have ${DEGREE_NAME[mineD]}` };

    // 5. Languages
    const needL = offerLanguages(body), langs = p.languages || {};
    const needs = Object.entries(needL);
    const names = { en: 'English', fr: 'French', de: 'German' };
    if (!needs.length) parts.languages = { v: 0.7, known: false, note: 'No language requirement found' };
    else {
      const worst = Math.min(...needs.map(([l, req]) => clamp((LVL[langs[l] || ''] || 0) / req)));
      parts.languages = { v: worst, known: true, note: needs.map(([l, r]) => names[l] + (r >= 4 ? ' required' : ' (offer language)') + (langs[l] ? `, you: ${langs[l]}` : ', not in profile')).join(' · ') };
    }

    // 6. Place and visa
    const order = p.countries || [], rank = order.indexOf(offer.c);
    let place = rank < 0 ? (offer.c === 'gl' ? 0.6 : 0.4) : 1 - rank * (0.5 / Math.max(1, order.length - 1));
    const remote = /\b(remote|teletravail|full remote|homeoffice|home office|anywhere|100% remote)\b/.test(body);
    if (remote && p.remote !== 'no') place = Math.min(1, place + 0.15);
    if (!remote && p.remote === 'yes') place -= 0.2;
    const needVisa = p.visa && p.visa[offer.c];
    let visaNote = '';
    if (needVisa) {
      if (/\b(visa (sponsor\w*|support|assistance)|sponsorship|relocation|we sponsor|aide a la relocalisation|visum)\b/.test(body)) { place = Math.min(1, place + 0.2); visaNote = ', visa or relocation offered'; }
      else if (/\b(eu citizens?|eu passport|right to work|work permit required|must be authori[sz]ed|nationalite (francaise|europeenne)|citoyen europeen|security clearance|habilitation)\b/.test(body)) { place -= 0.45; visaNote = ', work permit restriction'; }
    }
    parts.place = { v: clamp(place), known: true, note: (rank >= 0 ? `Country #${rank + 1} for you` : 'Country not in your list') + (remote ? ', remote possible' : '') + visaNote };

    // 7. Competition
    const age = daysSince(offer.posted, now) ?? (offer.foundAt ? Math.floor((now - offer.foundAt) / 864e5) : null);
    if (typeof offer.applicants === 'number') {
      const a = offer.applicants;
      parts.competition = { v: a < 10 ? 1 : a < 25 ? 0.85 : a < 50 ? 0.7 : a < 100 ? 0.5 : a < 200 ? 0.3 : 0.15, known: true, note: `${a}${offer.applicantsCapped ? '+' : ''} applicants` };
    } else if (age != null) parts.competition = { v: age <= 2 ? 0.9 : age <= 7 ? 0.7 : age <= 14 ? 0.5 : 0.3, known: false, note: `Applicants unknown, posted ${age} d ago` };
    else parts.competition = { v: 0.5, known: false, note: 'Applicants unknown' };

    // 8. Company reviews
    const co = offer.company;
    if (co && typeof co.rating === 'number') {
      const trust = clamp((co.count || 0) / 30), r = clamp((co.rating - 2.5) / 2);
      parts.company = { v: 0.5 + (r - 0.5) * trust, known: true, note: `${co.rating.toFixed(1)}/5 from ${co.count || '?'} reviews (${co.source})` };
    } else parts.company = { v: 0.5, known: false, note: 'No company reviews found' };

    // 9. Timing
    const left = offer.deadline ? -daysSince(offer.deadline, now) : null;
    if (left != null && left < 0) parts.timing = { v: 0, known: true, note: 'Deadline passed' };
    else if (left != null) parts.timing = { v: left <= 3 ? 0.7 : 1, known: true, note: left <= 7 ? `Deadline in ${left} d, apply soon` : `Deadline in ${left} d` };
    else if (age != null) parts.timing = { v: age <= 7 ? 1 : age <= 21 ? 0.7 : 0.4, known: true, note: `Posted ${age} d ago` };
    else parts.timing = { v: 0.6, known: false, note: 'Date unknown' };

    let total = 0, knownW = 0;
    for (const [k, w] of Object.entries(WEIGHTS)) { total += w * parts[k].v; if (parts[k].known) knownW += w; }
    const blockers = [];
    if (parts.languages.known && parts.languages.v < 0.5) blockers.push('Required language missing');
    if (visaNote === ', work permit restriction') blockers.push('Work permit restriction');
    if (parts.timing.v === 0) blockers.push('Deadline passed');
    if (parts.education.known && parts.education.v <= 0.1) blockers.push('Degree too low');
    if ((p.exclude || []).some((w) => w && termIn(w, norm(offer.title + ' ' + (offer.org || ''))))) blockers.push('Matches your exclusions');
    if (blockers.length) total = Math.min(total, 40);
    const urgent = left != null && left >= 0 && left <= 7;
    return { score: Math.round(total), confidence: knownW / 100, parts, urgent, blockers };
  }

  const profileFromCv = (text) => parseCv(text); // kept for older callers
  const api = { score, parseCv, profileFromCv, skillsIn, offerLevel, WEIGHTS, SKILL_NAMES: Object.keys(SKILLS), FAMILY, DEGREE_NAME, norm };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.ParcoursScore = api;
})(typeof window !== 'undefined' ? window : globalThis);
