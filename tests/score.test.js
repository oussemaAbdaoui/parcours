// Scoring engine regression set: real offers that were scored wrongly once, each with the verdict it must get.
// Run: node tests/score.test.js (exit code 1 on any failure). Every change to score.js must pass all cases.
const S = require('../score.js');

// A profile shaped like the app's owner: software/AI engineer, graduated 2026, 0.5 years, no internships.
const profile = {
  skills: ['python', 'java', 'javascript', 'machine learning', 'deep learning', 'llm', 'rag', 'agents', 'pytorch', 'langchain',
    'scikit-learn', 'backend', 'rest api', 'fastapi', 'flask', 'nestjs', 'vue', 'postgresql', 'docker', 'kubernetes', 'git'],
  years: 0.5, degree: { level: 3, name: "Master's or engineer", field: 'informatique et genie logiciel', year: 2026 },
  languages: { en: 'C1', fr: 'C1', ar: 'native' }, countries: ['fr', 'de', 'tn', 'be', 'se', 'gl'],
  visa: { fr: true, de: true, be: true, se: true }, internships: 'no', exclude: ['Senior'],
};
const NOW = Date.parse('2026-10-11T12:00:00Z');
const long = (s) => s + ' ' + 'Vous rejoindrez une équipe produit dynamique et participerez aux projets de digitalisation. '.repeat(6);
const req = (r) => ({ v: 1, degree_level: 'none', degree_strict: false, degree_fields: [], degree_fields_open: false, enrollment: 'none',
  min_years: -1, seniority: 'unknown', languages: [], work_auth: 'none', required_skills: [], evidence: '', ...r });
const job = (o) => ({ c: 'fr', kind: 'job', source: 'Test', posted: '2026-10-09', ...o });

const cases = [
  ['"mission principale" in a teaser is not a lead role (UNIMED, wrongly dropped)',
    job({ c: 'tn', title: 'Développeur Full Stack', desc: 'Nous recrutons un (e) Développeur full stack. Mission principal: Conception, développement et déploiement des solutions.' }),
    (r) => !r.sureBlockers.length],
  ['"mission principale" in a full text is not a lead role either',
    job({ title: 'Développeur Full Stack', desc: long('Mission principale : concevoir et développer des API REST en Python et Vue.js.') }),
    (r) => !r.blockers.includes('Too senior for your experience')],
  ['a pre-hire internship is open to graduates (Bestlab, wrongly dropped)',
    job({ c: 'tn', title: 'Stage pré-embauche – Développeur full stack (Laravel / Angular)', desc: 'À PROPOS DE BESTLAB…' }),
    (r) => !r.sureBlockers.length && !r.blockers.includes('Internship needs student status')],
  ['a regular end-of-studies internship needs student status',
    job({ title: 'Stage de fin d\'études - Data Scientist', desc: long('Stage de 6 mois en machine learning, Python.') }),
    (r) => r.blockers.includes('Internship needs student status')],
  ['a mid-level role is not a strong match at 0.5 years (Axon, scored 84)',
    job({ c: 'de', title: 'Mid-level Python Engineer - Agentic AI', desc: long('Build agentic AI systems in Python, LLM, RAG, Docker.'), req: req({ seniority: 'mid' }) }),
    (r) => r.score < 75],
  ['a LinkedIn offer with no description cannot rank strong (Catawiki, scored 79)',
    job({ c: 'de', source: 'LinkedIn', title: 'Backend Engineer', desc: '' }),
    (r) => !r.checked && r.score <= 65],
  ['"Agent commercial" is not an AI agent job',
    job({ c: 'tn', title: 'Agent commercial de comptoir', desc: 'Accueil clients' }),
    (r) => r.sureBlockers.includes('Outside your field')],
  ['"apprentissage" alone is an apprenticeship, not machine learning',
    job({ title: 'Contrat d\'apprentissage - Assistant comptable', desc: 'Saisie comptable' }),
    (r) => r.sureBlockers.includes('Outside your field')],
  ['a sales job around AI is still sales',
    job({ c: 'tn', title: 'Business Developer / Sales – Acquisition de leads Full IA H/F', desc: 'Prospection' }),
    (r) => r.sureBlockers.includes('Outside your field')],
  ['"Marketing Data Scientist" is a data science job (wrongly dropped)',
    job({ title: 'Marketing Data Scientist', desc: long('Machine learning models in Python, scikit-learn, SQL.') }),
    (r) => !r.blockers.includes('Outside your field')],
  ['a company hiring IT profiles is not an HR job (wrongly dropped)',
    job({ c: 'tn', title: 'Recrutement CDI – Profils IT & Digital : Cybersécurité, DevOps, Développement', desc: 'Nous recrutons' }),
    (r) => !r.sureBlockers.includes('Outside your field')],
  ['a degree in transportation engineering is another field (user report)',
    job({ title: 'AI Engineer - Mobility', desc: long('Master\'s degree in Transportation Engineering required. Python.'), req: req({ degree_level: 'master', degree_strict: true, degree_fields: ['civil_transport'] }) }),
    (r) => r.blockers.includes('Degree in another field')],
  ['a degree in mechanics or materials is another field (user report)',
    job({ title: 'Ingénieur simulation IA', desc: long('Master ou diplôme d\'ingénieur en mécanique ou science des matériaux. Python, IA.'), req: req({ degree_level: 'master', degree_strict: true, degree_fields: ['mechanical_materials'] }) }),
    (r) => r.blockers.includes('Degree in another field')],
  ['an internship for current PhD students is closed (user report)',
    job({ c: 'gl', title: '2026 Intern, PhD Research Scientist', desc: long('Pursuing a PhD degree in computer science or related field.'), req: req({ degree_level: 'master', enrollment: 'phd', seniority: 'intern' }) }),
    (r) => r.blockers.length > 0],
  ['a senior title is dropped before the text is read',
    job({ title: 'Senior Data Engineer', desc: 'Short teaser' }),
    (r) => r.sureBlockers.includes('Too senior for your experience')],
  ['a job written in Swedish needs Swedish (Platsbanken, scored 79)',
    job({ c: 'se', source: 'Platsbanken', title: 'Machine Learning Engineer', desc: 'Vi söker en Machine Learning Engineer som vill arbeta med AI och Python. Du kommer att arbeta i ett team som utvecklar modeller för kunder inom industrin. Vi har kontor i Stockholm och du ska ha erfarenhet av Python och maskininlärning. Hos oss får du arbeta med spännande projekt, och vi erbjuder flexibla arbetstider eller distansarbete. Tjänsten är på heltid och vi kommer att intervjua löpande.' }),
    (r) => r.blockers.includes('Required language missing')],
  ['Swedish required in Claude\'s reading counts (language "other")',
    job({ c: 'se', title: 'AI Engineer', desc: long('Python, LLM, RAG.'), req: req({ languages: [{ lang: 'other', level: 'fluent', required: true }] }) }),
    (r) => r.blockers.includes('Required language missing')],
  ['a French offer is not mistaken for Dutch',
    job({ title: 'Développeur Python IA', desc: long('Je recherche un développeur pour notre équipe en France. Vous travaillerez avec nous sur des projets IA en Python et les modèles de langage.') }),
    (r) => !r.blockers.includes('Required language missing')],
  ['an English offer in Sweden needs no Swedish',
    job({ c: 'se', title: 'Machine Learning Engineer', desc: long('We are looking for a machine learning engineer to join our team in Stockholm. You will work with Python, LLM and RAG, and our working language is English.') }),
    (r) => !r.blockers.includes('Required language missing')],
  ['a junior AI engineer job read in full is a strong match',
    job({ title: 'Junior AI Engineer (LLM, RAG)', desc: long('Profil : diplôme d\'ingénieur ou master en informatique. Python, LLM, RAG, LangChain, FastAPI, Docker. Débutant accepté. Anglais courant.'),
      req: req({ degree_level: 'master', degree_fields: ['computer_science', 'data_ai'], min_years: 0, seniority: 'entry', languages: [{ lang: 'en', level: 'fluent', required: true }] }) }),
    (r) => !r.blockers.length && r.score >= 75],
];

let failed = 0;
for (const [name, offer, ok] of cases) {
  const r = S.score(offer, profile, NOW);
  const pass = ok(r);
  if (!pass) failed++;
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${pass ? '' : `\n      score ${r.score}, checked ${r.checked}, blockers [${r.blockers}], sure [${r.sureBlockers}], seniority: ${r.parts.seniority.note}, field: ${r.parts.field.note}`}`);
}
console.log(`\n${cases.length - failed}/${cases.length} passed`);
process.exit(failed ? 1 : 0);
