/* Parcours match score and CV parser. Browser: window.ParcoursScore. Node: module.exports (tests).

   Score, 0-100, from ten signals (weights sum to 100):
     field 18        is the job in your field at all (title first; the body rescues titles that name no field)
     skills 26       your skills vs the offer; required skills weigh more than nice-to-haves, title mentions most,
                     a related skill in the same family (PyTorch for TensorFlow) earns half credit, and generic
                     skills (research, git, agile...) count a third
     role 6          offer title vs the roles and fields in your CV and saved searches
     seniority 18    experience: the years the offer asks vs yours, exactly when stated (2.5+ years short is a
                     dealbreaker), otherwise the level in the title (internship, junior, senior)
     education 5     degree asked (PhD, master's, engineer, bachelor) vs yours
     languages 8     languages required vs your levels
     place 8         country order, remote, visa sponsorship or work-permit restrictions
     competition 5   applicant count (LinkedIn), otherwise freshness
     company 3       company rating, weighted by review count
     timing 3        freshness and deadline
   Missing data scores neutral and lowers the confidence figure. Dealbreakers (including a title clearly outside
   your field) cap the score at 40; a title that names none of your fields caps it at 50. */
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
    // "optimisation de X" alone means improving anything (antennas, stoves), so only mathematical optimization counts.
    'optimization': ['opt', ['(?:mathematical|combinatorial|convex|stochastic|numerical|discrete|multi.objective|bayesian) optimi[sz]ation', 'optimi[sz]ation (?:algorithms?|solvers?|methods?|models?|problems?)',
      'optimi[sz]ation (?:mathematique|combinatoire|convexe|stochastique)', 'operations research', 'recherche operationnelle', 'or-tools', 'linear programming', 'integer programming', 'milp', 'gurobi', 'cplex', 'metaheuristics?']],
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
  // Level from the title first (clearest signal), then from the text, where only unambiguous phrases count
  // ("stage" alone also means "early-stage startup").
  function offerLevel(t, title) {
    if (title != null) {
      const tl = levelFromTitle(title);
      if (tl) return tl;
      if (/\b(internship|stage de fin d.etudes|stage (?:de|d.) ?\d|stagiaire|pfe|praktikum|werkstudent|alternance|apprentissage en alternance)\b/.test(t)) return { lvl: 0, label: 'internship' };
    } else if (/\b(stage|stagiaire|intern(ship)?|pfe|praktikum|werkstudent|alternance|apprenti)/.test(t)) return { lvl: 0, label: 'internship' };
    const ex = offerYears(t);
    const y = ex && ex.label !== 'Entry level' ? ex.min : null;
    if (/\b(principal|staff|head of|director|chef de|leiter)\b/.test(t) || /\blead\b(?! to)/.test(t) || (y !== null && y >= 8)) return { lvl: 4, label: 'lead', years: y };
    if (/\b(senior|sr\.?|confirme|experimente|erfahren)\b/.test(t) || (y !== null && y >= 5)) return { lvl: 3, label: 'senior', years: y };
    if (/\b(junior|jr\.?|graduate|debutant|entry.level|jeune diplome|berufseinsteiger|new grad)\b/.test(t) || (y !== null && y <= 2)) return { lvl: 1, label: 'junior', years: y };
    if (y !== null) return { lvl: 2, label: 'mid', years: y };
    return { lvl: null, label: 'not stated' };
  }
  /* Experience asked by an offer: {min, max, label} or null. Numbers only count near an experience word,
     so "3-year contract" or "5 days a week" are ignored. When several are stated, the strictest minimum wins. */
  const EXP_WORD = '(?:experience|exp\\.?|d.experience|erfahrung|berufserfahrung|work experience|professional experience|in (?:a|the) (?:similar|same) role)';
  const UNIT = '(?:years?|yrs?|ans?|annees?|jahre?n?)';
  function offerYears(text) {
    const t = norm(text);
    const found = [];
    const push = (min, max) => { if (min <= 20 && (max == null || (max >= min && max <= 25))) found.push({ min, max }); };
    let m;
    // "2-3 years of experience", "2 a 3 ans d'experience", "3 to 5 years", "3 bis 5 Jahre Berufserfahrung"
    const range = new RegExp('(\\d{1,2})\\s*(?:-|to|a|à|bis|et)\\s*(\\d{1,2})\\s*\\+?\\s*' + UNIT + '[^.;]{0,40}' + EXP_WORD + '|' + EXP_WORD + '[^.;\\d]{0,30}(\\d{1,2})\\s*(?:-|to|a|à|bis)\\s*(\\d{1,2})\\s*' + UNIT, 'g');
    while ((m = range.exec(t))) push(+(m[1] || m[3]), +(m[2] || m[4]));
    // "3+ years of experience", "minimum 3 ans d'experience", "at least 5 years", "mindestens 5 Jahre Berufserfahrung", "experience of 3 years"
    const single = new RegExp('(?:(?:at least|minimum|min\\.?|au moins|mindestens|plus de|more than|over)\\s*)?(\\d{1,2})\\s*\\+?\\s*' + UNIT + '(?:\\s*(?:\\+|or more|minimum|ou plus|und mehr))?[^.;]{0,40}' + EXP_WORD
      + '|' + EXP_WORD + '[^.;\\d]{0,30}(?:(?:at least|minimum|de|of|von|mindestens|d.au moins)\\s*)?(\\d{1,2})\\s*\\+?\\s*' + UNIT, 'g');
    while ((m = single.exec(t))) {
      const n = +(m[1] || m[2]);
      if (!found.some((f) => f.min === n || (f.max != null && n >= f.min && n <= f.max))) push(n, null);
    }
    if (found.length) {
      const f = found.reduce((a, b) => (b.min > a.min ? b : a));
      return { min: f.min, max: f.max, label: f.min === 0 && f.max ? `0–${f.max} yrs` : f.max != null ? `${f.min}–${f.max} yrs` : `${f.min}+ yrs` };
    }
    if (/\b(no experience (?:required|needed)|sans experience|debutant(?:e)?s? acceptes?|jeunes? diplomes?|entry.level|new grads?|graduate program|berufseinsteiger|keine berufserfahrung|junior)\b/.test(t)) return { min: 0, max: 2, label: 'Entry level' };
    return null;
  }

  function levelFromTitle(title) {
    const t = norm(title);
    if (/\b(stage|stagiaire|intern(ship)?|pfe|praktikum|werkstudent|alternance|alternant|apprenti)\b/.test(t)) return { lvl: 0, label: 'internship' };
    if (/\b(principal|staff|head of|director|directeur|chef de|leiter|vp|leader|professor|professeur|lecturer|maitre de conferences|faculty|tenure)\b/.test(t) || /\blead\b/.test(t)) return { lvl: 4, label: 'lead' };
    if (/\b(senior|sr\.?|confirme|experimente|expert)\b/.test(t)) return { lvl: 3, label: 'senior' };
    if (/\b(junior|jr\.?|graduate|debutant|entry.level|jeune diplome|new grad)\b/.test(t)) return { lvl: 1, label: 'junior' };
    return null;
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
  // Titles that need a doctorate already held: postdocs, professors, lecturers, faculty.
  const NEEDS_PHD_TITLE = /\b(post.?doc\w*|postdoctoral|post-doctoral|research fellow|professor\w*|professeur\w*|professur|lecturer|maitre de conferences|faculty|tenure.track|chaire|chair (?:in|of)|junior group leader)\b/;
  /* A doctorate in the requirements: 4 = required, 3.5 = preferred or "PhD or equivalent experience", 0 = not asked.
     Each mention is read in its own sentence: the PhD as the job itself (PhD student position, obtain a doctoral
     degree) does not count, an alternative (master's or PhD) or "desirable" makes it a preference. */
  function phdRequirement(t) {
    const re = /\b(ph\.?\s?d\.?|doctorate|doctoral degree|doctorat|docteur|promotion|promoviert\w*|dr\. rer\. nat\.?)\b/g;
    let level = 0, m;
    while ((m = re.exec(t))) {
      const word = m[1];
      const s0 = Math.max(t.lastIndexOf('.', m.index), t.lastIndexOf(';', m.index), t.lastIndexOf('•', m.index), m.index - 160);
      let s1 = t.slice(m.index).search(/[.;•]/); s1 = s1 < 0 ? t.length : m.index + s1;
      const sent = t.slice(s0 + 1, Math.min(s1, m.index + 160)), around = t.slice(Math.max(0, m.index - 40), m.index + 60);
      if (/^(promotion)$/.test(word) && !/abgeschlossen|completed|promotion in|promotion im/.test(around)) continue; // French "promotion 2026", marketing
      // The PhD is what the job offers, not what it asks: words attached to the mention ("PhD student", "PhD
      // position", "obtain a doctoral degree"), not anywhere in the sentence.
      const before = t.slice(Math.max(0, m.index - 32), m.index), after = t.slice(m.index + word.length, m.index + word.length + 28);
      if (/^\s*(?:\/\s*)?(students?|positions?|candidates?|candidature|programm?e?s?|studentships?|scholarships?|fellowships?|projects?|projets?|researchers?|research positions?|level|offers?|opportunit\w*|vacanc\w*|stelle\w*|&\s*post.?docs?|and post.?docs?|et post.?docs?|thesis in|en (?:informatique|ia) au sein)/.test(after)) continue;
      if (/\b(obtain|obtaining|pursue|pursuing|prepare|preparer|working towards|leading to|towards|complete|start|do|funded|fully funded|offers?|offering|ecole doctorale|doctoral school|candidat\w* au|inscription en|contrat de)\s+(?:a|an|the|your|un|une|le|la|son|votre)?\s*$/.test(before)) continue;
      // An alternative degree ("master's or PhD", "MSc/PhD") means a master's is enough: this mention asks nothing more.
      const alt = /\b(or|ou|oder)\s+(?:an?\s+)?(master\S*|msc|m\.sc|meng|engineer\S*|ingenieur\S*|bachelor\S*|bsc|diplom\S*)|(master\S*|msc|m\.sc|meng|ingenieur\S*|engineer\S*|bachelor\S*|diplom\S*)(?:\s+(?:degree|diplome|abschluss|in\s+\w+))?\s*(?:\/|or|ou|oder|,)\s*(?:an?\s+)?(?:ph\.?\s?d|doctora)/.test(sent);
      if (alt) continue;
      // Preferred, or replaceable by experience: a lower score, not a dealbreaker.
      const soft = /\b(or|ou|oder)\s+(?:an?\s+)?(equivalent|relevant|comparable|similar)|\b(desirable|desired|preferred|preferably|a plus|is a plus|an advantage|nice to have|bonus|ideally|souhaite\w*|apprecie\w*|serait un plus|von vorteil|wunschenswert|idealerweise)\b/.test(sent);
      const hard = /\b(ph\.?\s?d\.?|doctorate|doctoral degree|doctorat|promotion)\s+(in|en|im|degree|diplom\w*)\b|\b(hold|holds|holding|have|has|completed|finished|earned|obtained|titulaire|abgeschlossene|required|requis|mandatory|obligatoire|must|need|you bring|your profile|votre profil|qualifications?|minimum|ihr profil)\b/.test(sent);
      if (soft) level = Math.max(level, 3.5);
      else if (hard) return 4;
    }
    return level;
  }
  function offerDegree(t, title) {
    if (NEEDS_PHD_TITLE.test(norm(title || ''))) return 4;
    const phd = phdRequirement(t);
    if (phd) return phd;
    if (/\b(master.?s?|msc|m\.sc|bac\s*\+\s*5|engineering degree|diplome d.ingenieur|ecole d.ingenieurs?)\b/.test(t)) return 3;
    if (/\b(bachelor.?s?|licence|bac\s*\+\s*3|bsc)\b/.test(t)) return 2;
    return 0;
  }
  function daysSince(iso, now) { const t = Date.parse(iso || ''); return isNaN(t) ? null : Math.floor((now - t) / 864e5); }

  // Families where knowing one member says little about another (Python does not make you a Java developer).
  const NO_PARTIAL = new Set(['lang', 'research', 'method', 'tools', 'mobile', 'sec', 'embedded']);
  // Skills almost every offer mentions: they say little about fit, so they count a third.
  const GENERIC_SKILLS = new Set(['research', 'monitoring', 'git', 'agile', 'testing', 'linux', 'security', 'statistics', 'docker', 'sql']);
  const WEIGHTS = { field: 18, skills: 26, role: 6, seniority: 18, education: 5, languages: 8, place: 8, competition: 5, company: 3, timing: 3 };

  /* Field fit: does the job belong to your field at all? Fields come from the skill families in your profile.
     The title decides first (it names the job); the body only rescues titles that name no field, such as a PhD
     topic that applies machine learning to another domain. */
  const FIELDS = {
    ai: { fams: ['ml', 'llm', 'nlp', 'xai', 'ir', 'cv', 'dlfw', 'llmfw', 'mllib', 'mlops'],
      title: /\b(machine learning|ml|ai|ia|a\.i\.|artificial intelligence|intelligence artificielle|kunstliche intelligenz|ki|deep learning|apprentissage|neural|nlp|llms?|genai|generative|computer vision|vision par ordinateur|data scien\w*|mlops|research (?:engineer|scientist)|applied scientist|prompt|rag|agents?|perception|reinforcement|model (?:optimi[sz]ation|training|evaluation)|inference|quantization|embeddings?)\b/ },
    data: { fams: ['data', 'db', 'nosql'],
      title: /\b(data|donnees|daten|analytics|bi|business intelligence|big data|etl|statisti\w*|quant\w*|analyst|analyste)\b/ },
    software: { fams: ['backend', 'api', 'pyweb', 'jvmweb', 'jsweb', 'phpweb', 'front', 'devops', 'cloud', 'lang', 'mobile'],
      title: /\b(software|logiciel|softwareentwickl\w*|developer|developpeur|entwickler|programmer|programmeur|backend|back.end|full.?stack|frontend|front.end|devops|sre|cloud|platform|plateforme|web|api|python|java|typescript|node|informati\w*|systems? engineer|ingenieur (?:etudes et )?developpement)\b/ },
    research: { fams: ['research', 'opt', 'xai'],
      title: /\b(phd|ph\.d|doctora\w*|doktorand\w*|these|thesis|research|recherche|forschung|postdoc|scientist|chercheur)\b/ },
  };
  const OFF_FIELD = /\b(account (?:executive|manager)|ae|sales|vente\w*|vendeu\w*|verkauf\w*|vertrieb\w*|commercia\w*|business development|business developer|bdr|sdr|marketing|growth|customer success|support agent|recrui\w*|recrut\w*|talent acquisition|engagement manager|services manager|human resources|ressources humaines|\bhr\b|\brh\b|accountant|comptab\w*|finance manager|lawyer|juriste|avocat|nurse|infirmi\w*|medecin|physician|pharmacist|teacher|enseignant|instituteur|chauffeur|driver|electricien|electrician|mecanicien|mechanic|technicien de maintenance|plombier|soudeur|cuisinier|chef de rang|serveur|receptionist|assistant(?:e)? (?:de direction|administrati\w*)|office manager|community manager|graphic designer|graphiste|copywriter|translator|traducteur|management consultant|strategist|partnerships?|logisti\w*|supply chain|procurement|achat\w*|architecte? d.interieur|immobilier|real estate|insurance|assurance)\b/;
  function myFields(p) {
    const fams = new Set((p.skills || []).map((k) => FAMILY[k]));
    const out = Object.entries(FIELDS).filter(([, f]) => f.fams.filter((x) => fams.has(x)).length >= 1).map(([k]) => k);
    return out.length ? out : Object.keys(FIELDS);
  }
  function fieldFit(offer, p, title, body) {
    const fields = myFields(p);
    const hitTitle = fields.filter((f) => FIELDS[f].title.test(title));
    const mine = new Set(p.skills || []);
    const titleSkills = skillsIn(offer.title).filter((k) => !GENERIC_SKILLS.has(k));
    const myTitleSkills = titleSkills.filter((k) => mine.has(k) || fields.some((f) => FIELDS[f].fams.includes(FAMILY[k])));
    const off = OFF_FIELD.test(title);
    // Research titles alone (a PhD in fluid mechanics) do not make the job yours: they need a topic from your other fields.
    const coreHit = hitTitle.filter((f) => f !== 'research');
    if ((coreHit.length || myTitleSkills.length) && !off) {
      return { v: 1, known: true, off: false, note: `In your field: ${[...coreHit, ...myTitleSkills].slice(0, 3).join(', ')}` };
    }
    // "Commercial IT", "Sales Engineer - SaaS": the job itself is sales or HR even if the product is software.
    if (off && coreHit.includes('ai')) return { v: 0.4, known: true, off: false, note: `Mostly ${title.match(OFF_FIELD)[0]}, around AI` };
    const coreFams = new Set(fields.filter((f) => f !== 'research').flatMap((f) => FIELDS[f].fams));
    const bodySkills = skillsIn(body).filter((k) => !GENERIC_SKILLS.has(k) && coreFams.has(FAMILY[k]));
    const dense = bodySkills.length >= 3;
    if (off) return { v: 0, known: true, off: true, note: `Outside your field (${title.match(OFF_FIELD)[0]})` };
    if (hitTitle.includes('research') || offer.kind === 'phd') {
      return dense ? { v: 0.6, known: true, off: false, note: `Research applying your skills: ${bodySkills.slice(0, 3).join(', ')}` }
        : { v: 0.1, known: true, off: bodySkills.length === 0, note: 'Research topic outside your field' };
    }
    if (dense) return { v: 0.55, known: true, off: false, note: `Title names no field; the offer asks ${bodySkills.slice(0, 3).join(', ')}` };
    // No field in the title and none of your skills in the text: a different job (video editor, bookkeeper).
    return { v: bodySkills.length ? 0.3 : 0.1, known: true, off: !bodySkills.length && body.length > 200, note: 'Title outside your field' };
  }
  const ROLE_GENERIC = new Set(['engineer', 'ingenieur', 'developer', 'developpeur', 'h/f', 'f/h', 'm/w/d', 'intern', 'stage', 'senior', 'junior', 'and', 'et', 'de', 'en', 'in', 'of', 'the', 'for', 'a', 'position', 'poste']);

  /* ---------- ideas adapted from Resume-Matcher (srbhr/Resume-Matcher), without an LLM ----------
     1. Offer keywords: the terms that make an offer specific (graph neural networks, telecom, fintech), found
        statistically: frequent in the offer, rare across all collected offers (TF-IDF). Their share in your CV is
        Resume-Matcher's keyword match, which there comes from an LLM.
     2. Skill evidence: a skill used in a job or project counts more than a skill only listed, and the CV lines
        that best support an offer are shown (Resume-Matcher scores resume bullets for relevance).
     3. CV ATS check: sections, contact details, measurable results and length (its section completeness). */
  const KW_STOP = new Set(('a an the and or of to in on for with at by from as is are be will you your we our us they their this that these those it its into over per via ' +
    'le la les un une des du de d l et ou en au aux pour par sur avec dans vous nous notre nos votre vos est sont sera ce cette ces qui que dont ' +
    'der die das ein eine und oder mit fur von zu im in auf bei wir sie ihr ihre unser unsere ist sind als auch ' +
    'experience experiences team teams work working job jobs role position poste candidate candidat profil profile company entreprise offre offer ' +
    'years year ans annees jahre strong good excellent great new solid ability skills skill knowledge competences connaissances required requis ' +
    'responsibilities missions mission tasks taches looking recherchons join rejoindre opportunity apply benefits salary salaire contract contrat cdi cdd ' +
    'h f m w d h/f f/h m/w/d plus etc including include such like within across based well using use used make help ' +
    'university universite universitat institut institute school ecole laboratory laboratoire lab phd doctorant doctoral doctorat these thesis postdoc post ' +
    'analysis analyse system systems systeme study etude development developpement engineer ingenieur research recherche project projet ' +
    'paris lyon rennes grenoble saclay sophia antipolis nancy lille bordeaux toulouse marseille nantes strasbourg montpellier nice orsay versailles palaiseau ' +
    'berlin munich munchen hamburg frankfurt stuttgart darmstadt zurich geneva geneve lausanne bern basel montreal toronto quebec vancouver ottawa ' +
    'tunis sfax sousse ariana monastir bizerte nabeul london cambridge oxford amsterdam brussels madrid barcelona milan rome remote hybrid ' +
    'inria cnrs cea inserm ird inrae mines telecom sorbonne france germany deutschland canada switzerland suisse tunisia tunisie europe').split(' '));
  const termsOf = (text, skip) => {
    const tf = new Map();
    // Two-word terms only within a phrase: punctuation (". , ; : ( ) | /") ends one.
    for (const phrase of String(text || '').toLowerCase().split(/[.,;:!?()[\]|/\n•]+/).map(norm)) {
      let prev = null;
      for (const w of phrase.split(/[^a-z0-9+#]+/)) {
        const ok = w.length >= 3 && !KW_STOP.has(w) && !/^\d+$/.test(w) && !(skip && skip.has(w));
        if (!ok) { prev = null; continue; }
        tf.set(w, (tf.get(w) || 0) + 1);
        if (prev) tf.set(prev + ' ' + w, (tf.get(prev + ' ' + w) || 0) + 1.5); // only words that were next to each other
        prev = w;
      }
    }
    return tf;
  };
  const nameWords = (o) => new Set(norm((o.org || '') + ' ' + (o.location || '')).split(/[^a-z0-9]+/).filter((w) => w.length >= 3));
  const offerText = (o) => (o.title || '') + ' . ' + (o.title || '') + ' . ' + (o.desc || ''); // the title counts twice
  // TF-IDF vector (L2-normalised) over the collection's document frequencies.
  function tfidf(tf, idf) {
    const v = new Map();
    let n2 = 0;
    for (const [t, f] of tf) {
      const d = idf.df.get(t) || 0;
      if (d / idf.n > 0.3) continue; // in a third of all offers: boilerplate
      const w = (1 + Math.log(f)) * Math.log((idf.n + 1) / (d + 1));
      v.set(t, w);
      n2 += w * w;
    }
    const n = Math.sqrt(n2) || 1;
    for (const [t, w] of v) v.set(t, w / n);
    return v;
  }
  const cosine = (a, b) => { let s = 0; const [x, y] = a.size < b.size ? [a, b] : [b, a]; for (const [t, w] of x) { const u = y.get(t); if (u) s += w * u; } return s; };
  /* Document frequency over the collected offers, built once per collection (app) or batch (collector).
     With a CV it also stores the CV vector and a reference similarity (the 90th percentile over all offers), so a
     single offer's similarity reads as "how close to your best matches". */
  function buildIdf(offers, cv) {
    const df = new Map(), list = offers || [];
    for (const o of list) for (const t of termsOf(offerText(o), nameWords(o)).keys()) df.set(t, (df.get(t) || 0) + 1);
    const idf = { n: list.length, df, cvVec: null, ref: null };
    if (cv && list.length >= 20) {
      idf.cvVec = tfidf(termsOf(cv), idf);
      const sims = list.map((o) => cosine(idf.cvVec, tfidf(termsOf(offerText(o), nameWords(o)), idf))).sort((a, b) => a - b);
      idf.ref = Math.max(0.01, sims[Math.floor(sims.length * 0.9)]);
      idf.sims = [0.1, 0.5, 0.9, 0.99].map((q) => +sims[Math.floor(sims.length * q)].toFixed(3));
    }
    return idf;
  }
  // The offer's most specific terms and whether your CV has them (shown in "Why"; the score uses the cosine).
  function offerKeywords(offer, idf, k = 10) {
    if (!idf || idf.n < 20) return [];
    const v = tfidf(termsOf(offerText(offer), nameWords(offer)), idf);
    const out = [...v].sort((a, b) => b[1] - a[1]), picked = [];
    for (const [t, w] of out) { if (picked.length >= k) break; if (!picked.some(([u]) => u.includes(t) || t.includes(u))) picked.push([t, w]); }
    return picked;
  }
  // "LIPN, Sorbonne University  May – Sept 2026  Engineer, Intern": a year and a dash without an action verb.
  const ACTION = /\b(built|build|designed|design|developed|develop|implemented|led|created|trained|deployed|improved|achieved|reduced|increased|automated|analy[sz]ed|wrote|published|conçu|concu|developpe|realise|mis en place|optimi[sz]ed)\b/i;
  const isHeaderLine = (b) => /\b(19|20)\d{2}\b/.test(b) && /[-–]/.test(b) && !ACTION.test(b);
  // Per-CV index, computed once per CV text: full text, skills backed by experience or projects, and bullet lines.
  let cvMemo = { key: null, val: null };
  function cvIndex(cv) {
    const raw = String(cv || '');
    if (cvMemo.key === raw) return cvMemo.val;
    const secs = sections(raw);
    const work = [secs.experience, secs.projects, secs.publications].filter(Boolean).join(' \n ');
    const bullets = (work || raw).split(/\s*(?:[•▪●◦·]|\n|\s-\s|(?<=[.;])\s+(?=[A-Z]))\s*/).map((b) => b.trim()).filter((b) => b.length >= 40 && b.length <= 400 && !rangesIn(b, Date.now()).length && !isHeaderLine(b)); // dated lines are job headers, not achievements
    const val = { text: ' ' + norm(raw) + ' ', evidenced: new Set(skillsIn(work)), bullets, hasSections: !!work };
    cvMemo = { key: raw, val };
    return val;
  }
  // ATS readiness of the CV itself (Profile page).
  function atsCheck(cv) {
    const raw = String(cv || ''), t = norm(raw), secs = sections(raw), words = (t.match(/[a-z]{2,}/g) || []).length;
    const checks = [
      { ok: !!secs.experience, label: 'Experience section', tip: 'Add a heading "Experience" (or "Expérience professionnelle") so ATS software can find your jobs and internships.' },
      { ok: !!secs.education, label: 'Education section', tip: 'Add a heading "Education" with your degree, school and dates.' },
      { ok: !!secs.skills, label: 'Skills section', tip: 'List your tools and languages under a "Skills" heading: ATS software reads that section first.' },
      { ok: !!(secs.summary || secs.projects), label: 'Summary or projects', tip: 'A 2-3 line summary naming the role you want helps both ATS keyword matching and recruiters.' },
      { ok: /\S+@\S+\.\S+/.test(raw), label: 'Email address', tip: 'Put your email in the header as plain text.' },
      { ok: /\+?\d[\d\s().-]{7,}/.test(raw), label: 'Phone number', tip: 'Add a phone number with country code (+216 …).' },
      { ok: /linkedin\.com|github\.com/.test(t), label: 'LinkedIn or GitHub', tip: 'Add your LinkedIn or GitHub URL; many recruiters check them first.' },
      { ok: (raw.match(/\d+\s?(?:%|x\b|k\b|ms\b|users|utilisateurs|million|accuracy|precision|f1)/gi) || []).length >= 2, label: 'Measurable results', tip: 'Quantify at least two achievements (accuracy +7%, 3x faster, 10k users).' },
      { ok: words >= 250 && words <= 1100, label: `Length (${words} words)`, tip: words < 250 ? 'The CV looks short for ATS matching; describe projects and tools in more detail.' : 'The CV is long; one page (two with publications) reads better and parses more reliably.' },
      { ok: skillsIn(raw).length >= 8, label: `Recognised skills (${skillsIn(raw).length})`, tip: 'Name your tools explicitly (PyTorch, Docker, PostgreSQL…) rather than only describing them.' },
      { ok: rangesIn(raw, Date.now()).length >= 1, label: 'Dated experience', tip: 'Give each job and internship a date range (Jun 2025 - Sep 2025) so your experience can be counted.' },
    ];
    return { score: Math.round(100 * checks.filter((c) => c.ok).length / checks.length), checks };
  }

  function score(offer, profile, now = Date.now(), ctx = {}) {
    const p = profile || {};
    const tRaw = (offer.title || '') + ' . ' + (offer.desc || '') + ' . ' + (offer.type || '');
    const body = norm(tRaw), title = norm(offer.title);
    const parts = {};

    // 0. Field: is this job in your field at all?
    parts.field = fieldFit(offer, p, title, body);

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
      // Skills used in a job or project count fully; skills only listed count 80% (when the CV has those sections).
      const cvx = p.cv ? cvIndex(p.cv) : null, backed = (k) => !cvx || !cvx.hasSections || cvx.evidenced.has(k);
      for (const k of wanted) {
        const w = (inTitle.has(k) ? 2.5 : inReq.has(k) ? 1.6 : inNice.has(k) ? 0.5 : 1) * (GENERIC_SKILLS.has(k) ? 0.35 : 1);
        total += w;
        if (mine.has(k)) { got += w * (backed(k) ? 1 : 0.8); have.push(k); }
        else if (myFamilies.has(FAMILY[k]) && !NO_PARTIAL.has(FAMILY[k])) { got += w * 0.5; related.push(k); }
        else missing.push({ k, w });
      }
      // Rare terms from your CV that the offer names literally are strong evidence.
      got += extraHits.length * 1.5; total += extraHits.length * 1.5;
      // Evidence shrinkage: a couple of matched words is weak evidence, so few-skill offers are pulled toward neutral.
      const K = 3, cover = (got + 0.4 * K) / (total + K);
      missing.sort((a, b) => b.w - a.w);
      // Whole-text similarity between your CV and the offer (TF-IDF cosine, relative to your best matches): a fifth
      // of the skills signal when the collection is large enough to weigh terms.
      let kwNote = '', kwHave = [], kwMissing = [], v = clamp(0.05 + 0.95 * cover);
      if (cvx && ctx.idf && ctx.idf.cvVec) {
        const sim = cosine(ctx.idf.cvVec, tfidf(termsOf(offerText(offer), nameWords(offer)), ctx.idf));
        const rel = clamp(sim / ctx.idf.ref);
        v = clamp(0.8 * v + 0.2 * rel);
        for (const [t] of offerKeywords(offer, ctx.idf)) (cvx.text.includes(' ' + t + ' ') ? kwHave : kwMissing).push(t);
        kwNote = ` · CV similarity ${Math.round(rel * 100)}% of your best matches`;
      }
      // CV lines that best support this offer: most matched skills and keywords.
      const evidence = cvx ? cvx.bullets.map((b) => { const nb = ' ' + norm(b) + ' '; const hits = skillsIn(b).filter((k) => have.includes(k)).length + kwHave.filter((t) => nb.includes(' ' + t + ' ')).length; return [b, hits]; })
        .filter(([, h]) => h >= 2).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([b]) => b.length > 160 ? b.slice(0, 157) + '…' : b) : [];
      parts.skills = {
        v, known: total >= 3,
        note: `${have.length + extraHits.length} of ${wanted.length + extraHits.length} matched: ${[...have, ...extraHits].slice(0, 6).join(', ') || 'none'}${related.length ? ` · related: ${related.slice(0, 3).join(', ')}` : ''}${kwNote}`,
        missing: missing.slice(0, 5).map((m) => m.k + (inReq.has(m.k) || inTitle.has(m.k) ? ' (required)' : '')),
        keywords: { have: kwHave.slice(0, 6), missing: kwMissing.slice(0, 6) }, evidence,
      };
    }

    // 2. Role fit: offer title vs your roles, fields and searches
    const roleWords = new Set();
    [...(p.roles || []), ...(p.targets || [])].forEach((r) => norm(r).split(/[^a-z0-9+#]+/).forEach((w) => { if (w.length > 1 && !ROLE_GENERIC.has(w)) roleWords.add(w); }));
    const titleSkills = [...inTitle].filter((k) => !GENERIC_SKILLS.has(k));
    if (!roleWords.size && !mine.size) parts.role = { v: 0.5, known: false, note: 'No roles in profile' };
    else {
      const tw = title.split(/[^a-z0-9+#]+/).filter((w) => w.length > 1 && !ROLE_GENERIC.has(w));
      const hitW = tw.filter((w) => roleWords.has(w));
      const hitS = titleSkills.filter((k) => mine.has(k));
      const v = tw.length ? clamp((hitW.length + hitS.length * 1.2) / Math.min(3, tw.length)) : 0.5;
      parts.role = { v: clamp(0.15 + 0.85 * v), known: tw.length > 0, note: hitW.length || hitS.length ? `Title matches: ${[...new Set([...hitW, ...hitS])].slice(0, 4).join(', ')}` : 'Title outside your roles and fields' };
    }

    // 3. Seniority
    const lv = offerLevel(body, offer.title || "");
    let tooSenior = false;
    const asked = offerYears(body), mineY = p.years ?? 0;
    if (offer.kind === 'phd' || offer.kind === 'master') parts.seniority = { v: mineY <= 4 ? 1 : 0.7, known: true, note: offer.kind === 'phd' ? 'PhD position' : "Master's programme" };
    else if (asked && lv.lvl !== 0) {
      // Years stated in the offer: compare them exactly with yours (the strongest signal of what the job expects).
      if (asked.label === 'Entry level') parts.seniority = { v: mineY <= 3 ? 1 : 0.8, known: true, note: `Entry level, you have ${mineY} yrs` };
      else {
        const gap = asked.min - mineY;
        tooSenior = gap >= 2.5 || (lv.lvl != null && lv.lvl - profileLevel(mineY) >= 1.5);
        const v = gap <= 0 ? (asked.max != null && mineY > asked.max + 3 ? 0.7 : 1) : gap <= 1 ? 0.75 : gap <= 2 ? 0.4 : 0.02;
        parts.seniority = { v, known: true, note: `Asks ${asked.label} of experience, you have ${mineY} yrs${gap > 0 ? ` (${Math.round(gap * 10) / 10} short)` : ''}` };
      }
    }
    else if (lv.lvl === null) parts.seniority = { v: 0.5, known: false, note: 'Experience not stated' };
    else {
      const gap = lv.lvl - profileLevel(p.years);
      tooSenior = gap >= 1.5;
      const v = gap <= -2 ? 0.55 : gap <= 0 ? 1 : gap <= 1 ? 0.6 : gap <= 2 ? 0.25 : 0.05;
      parts.seniority = { v, known: true, note: `Asks ${lv.label}${lv.years != null ? ` (${lv.years}+ yrs)` : ''}, you have ${p.years ?? 0} yrs` };
    }

    // 4. Education
    // Postdocs, professorships and lecturer posts need a PhD even when the collector filed them with PhD offers;
    // PhD positions themselves ask for a master's (their texts say "PhD in ..." about the job, not the candidate).
    const need = NEEDS_PHD_TITLE.test(title) ? 4 : offer.kind === 'phd' ? 3 : offerDegree(body, offer.title), mineD = (p.degree && p.degree.level) || 0;
    const needName = need === 3.5 ? 'a PhD (or equivalent experience)' : DEGREE_NAME[need];
    if (!need) parts.education = { v: 0.5, known: false, note: 'No degree stated' };
    else if (!mineD) parts.education = { v: 0.5, known: false, note: `Asks ${needName}, add your degree in Profile` };
    else if (need === 3.5) parts.education = { v: mineD >= 4 ? 1 : mineD === 3 ? 0.4 : 0.15, known: true, note: `Prefers ${needName}, you have ${DEGREE_NAME[mineD]}` };
    else parts.education = { v: mineD >= need ? 1 : need === 4 ? 0.05 : mineD === need - 1 ? 0.45 : 0.1, known: true, note: `${need === 4 ? 'Requires' : 'Asks'} ${needName}, you have ${DEGREE_NAME[mineD]}` };

    // 5. Languages
    const needL = offerLanguages(body), langs = p.languages || {};
    const needs = Object.entries(needL);
    const names = { en: 'English', fr: 'French', de: 'German' };
    if (!needs.length) parts.languages = { v: 0.5, known: false, note: 'No language requirement found' };
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
    else parts.timing = { v: 0.5, known: false, note: 'Date unknown' };

    let total = 0, knownW = 0;
    for (const [k, w] of Object.entries(WEIGHTS)) { total += w * parts[k].v; if (parts[k].known) knownW += w; }
    const blockers = [];
    if (parts.field.off) blockers.push('Outside your field');
    if (parts.languages.known && parts.languages.v < 0.5) blockers.push('Required language missing');
    if (visaNote === ', work permit restriction') blockers.push('Work permit restriction');
    if (parts.timing.v === 0) blockers.push('Deadline passed');
    if (parts.education.known && parts.education.v <= 0.1) blockers.push('Degree too low');
    if (tooSenior) blockers.push('Too senior for your experience');
    // Internships and work-study need student status: closed once you have graduated (September of your
    // graduation year), unless your profile says you can still take them.
    const d = new Date(now), gy = p.degree && p.degree.year;
    const graduated = !!gy && (d.getFullYear() > gy || (d.getFullYear() === gy && d.getMonth() >= 8));
    const canIntern = p.internships === 'yes' || (p.internships !== 'no' && !graduated);
    if (lv.lvl === 0 && offer.kind !== 'phd' && !canIntern) blockers.push('Internship needs student status');
    // Jobs reserved for current students (student assistant, Werkstudent, "currently enrolled"), same rule.
    else if (offer.kind !== 'phd' && !canIntern && /\b(currently enrolled|must be (?:a |an )?(?:current |enrolled )?students?|enrolled (?:in|at) (?:a |an )?(?:university|bachelor|master)|student assistant|working student|werkstudent\w*|studentische (?:hilfskraft|mitarbeiter)|job etudiant|etudiant\w* en (?:cours|derniere annee)|en cours de (?:formation|cursus)|immatrikuliert)\b/.test(body)) blockers.push('Reserved for current students');
    if ((p.exclude || []).some((w) => w && termIn(w, norm(offer.title + ' ' + (offer.org || ''))))) blockers.push('Matches your exclusions');
    if (blockers.length) total = Math.min(total, 40);
    else if (parts.field.v < 0.3) total = Math.min(total, 50); // a job outside your field never ranks with real matches
    const urgent = left != null && left >= 0 && left <= 7;
    const conf = knownW / 100;
    return { score: Math.round(total), confidence: conf, rank: total - (1 - conf) * 12, parts, urgent, blockers };
  }

  const profileFromCv = (text) => parseCv(text); // kept for older callers
  const api = { score, parseCv, profileFromCv, skillsIn, offerLevel, offerYears, buildIdf, offerKeywords, atsCheck, WEIGHTS, SKILL_NAMES: Object.keys(SKILLS), FAMILY, DEGREE_NAME, norm };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.ParcoursScore = api;
})(typeof window !== 'undefined' ? window : globalThis);
