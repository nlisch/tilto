"""
Données SEO programmatiques — hand-curated content pour les pages métiers et villes.

Chaque entrée alimente une page indexable Google avec :
- H1 + meta description ciblés sur la requête
- Intro empathique (~150 mots)
- Pain points / leviers / pistes alternatives
- Stat marché crédible
- CTA vers le diagnostic Tilto

Pourquoi du contenu écrit à la main et pas généré par LLM ?
Google a renforcé ses pénalités sur le contenu massivement AI-generated
(updates "helpful content" 2023+). Mieux vaut 10 pages bien écrites
qui ranquent que 100 pages génériques pénalisées.
"""

# ─────────────────────────────────────────────────────────────────────────────
# MÉTIERS — Top 10 reconversions courantes en France
# ─────────────────────────────────────────────────────────────────────────────

METIERS = {
    'commercial': {
        'slug': 'commercial',
        'name': 'commercial·e',
        'name_singulier_h': 'un·e commercial·e',
        'h1': 'Commercial·e en quête de sens : par où commencer ta reconversion ?',
        'meta_description': "Tu es commercial·e et tu veux changer de voie ? Découvre 3 pistes carrière concrètes en 5 min, basées sur le marché de l'emploi. Gratuit.",
        'intro': "Les métiers commerciaux usent. Pression sur les chiffres, courses aux quotas, relations transactionnelles, sentiment de ne pas créer quelque chose qui dure. C'est l'un des profils les plus représentés dans les reconversions en France — et c'est tout sauf un échec. Tu as développé des compétences ultra-transférables (négociation, écoute, persuasion, résilience) qui ouvrent énormément de portes en dehors de la vente classique.",
        'pain_points': [
            "Pression constante sur les objectifs",
            "Sentiment de ne plus créer de valeur tangible",
            "Relations clients superficielles",
            "Burnout latent ou avéré",
        ],
        'alt_paths': [
            {'name': 'Customer Success Manager', 'why': "tes compétences relationnelles servent un produit que tu défends"},
            {'name': 'Product Marketing Manager', 'why': "tu connais déjà la voix client mieux que personne"},
            {'name': 'Coach professionnel', 'why': "tu accompagnes les autres au lieu de leur vendre"},
            {'name': 'Recruteur·euse', 'why': "tu retrouves le relationnel sans la pression chiffres"},
        ],
        'stat': "Plus de 30% des commerciaux envisagent une reconversion dans les 5 prochaines années (source : Apec, 2024).",
        'cta_hook': "Tu n'es pas seul·e. Discute 5 minutes avec Claire et reçois 3 pistes concrètes adaptées à ton profil de commercial·e.",
    },
    'marketing-manager': {
        'slug': 'marketing-manager',
        'name': 'marketing manager',
        'name_singulier_h': 'un·e marketing manager',
        'h1': 'Marketing manager fatigué·e : 3 pistes carrière qui ont du sens',
        'meta_description': "Tu es marketing manager et tu cherches autre chose ? 5 min de conversation pour découvrir 3 pistes adaptées à ton profil et au marché.",
        'intro': "Marketing en scale-up, marketing en agence, marketing en grand groupe : peu importe le contexte, on retrouve les mêmes signaux de ras-le-bol. Trop de reportings, trop de réunions, des KPIs qui ne disent rien sur la valeur réelle créée, et la sensation de raconter des histoires sans vraiment les vivre. Pourtant ton expérience produit, ton sens du storytelling et ta culture data sont des atouts rares dans des secteurs en demande.",
        'pain_points': [
            "Sur-réunions et reportings sans fin",
            "Métriques déconnectées de l'impact réel",
            "Pression croissance court-termiste",
            "Distance avec l'utilisateur final",
        ],
        'alt_paths': [
            {'name': 'Product Manager', 'why': "construire le produit au lieu de le promouvoir"},
            {'name': 'Communication ESS / asso', 'why': "remettre le sens et l'impact au centre"},
            {'name': 'Indépendant·e en stratégie', 'why': "choisir tes clients selon tes valeurs"},
            {'name': 'Content / podcast', 'why': "raconter de vraies histoires longues"},
        ],
        'stat': "Les profils marketing avec 5+ ans d'expérience sont parmi les plus recherchés dans les startups à impact (source : Welcome to the Jungle, 2025).",
        'cta_hook': "Échange 5 min avec Claire et découvre 3 pistes alignées avec ce qui t'anime — pas avec ce que ton CV dit que tu dois faire.",
    },
    'ingenieur': {
        'slug': 'ingenieur',
        'name': 'ingénieur·e',
        'name_singulier_h': 'un·e ingénieur·e',
        'h1': 'Ingénieur·e en reconversion : explorer hors du scientifique',
        'meta_description': "Ingénieur·e qui veut changer de voie ? Découvre 3 pistes carrière concrètes, basées sur tes compétences et le marché. 5 min, gratuit.",
        'intro': "Tu as fait un parcours scientifique exigeant, parfois prestigieux, et pourtant aujourd'hui tu te demandes pourquoi tu ne vibres plus. Ingénierie qui devient routine, projets qui s'enchaînent sans cohérence, distance avec l'humain. Bonne nouvelle : la rigueur d'analyse et la capacité à structurer un problème complexe que tu as développées sont infiniment valorisables ailleurs — y compris dans des univers très éloignés de ta formation initiale.",
        'pain_points': [
            "Manque de dimension humaine ou créative",
            "Sentiment d'être enfermé·e par son diplôme",
            "Travail intellectuellement répétitif",
            "Perte du sens de l'utilité concrète",
        ],
        'alt_paths': [
            {'name': 'Product Manager tech', 'why': "tu gardes la tech mais tu pilotes la stratégie"},
            {'name': 'Conseil ESS / impact', 'why': "ta rigueur sert des projets qui changent les choses"},
            {'name': 'Enseignement / médiation scientifique', 'why': "transmettre au lieu de produire"},
            {'name': 'Entrepreneuriat technique', 'why': "construire le tien plutôt que de l'exécuter"},
        ],
        'stat': "Près d'un·e ingénieur·e sur deux envisage une évolution hors de son domaine technique d'origine après 10 ans (source : IESF, 2024).",
        'cta_hook': "Discute 5 min avec Claire et reçois 3 pistes concrètes qui valorisent tes compétences au-delà de ton diplôme.",
    },
    'developpeur': {
        'slug': 'developpeur',
        'name': 'développeur·euse',
        'name_singulier_h': 'un·e développeur·euse',
        'h1': 'Développeur·euse : et si tu changeais sans tout perdre ?',
        'meta_description': "Tu es dev et tu sens que tu veux autre chose ? 5 min de conversation pour 3 pistes qui valorisent ton profil tech. Gratuit, confidentiel.",
        'intro': "Le code peut être passionnant, mais après 5, 8, 10 ans dans le métier, beaucoup de devs ressentent une lassitude différente : envie d'impact plus visible, besoin de plus de relationnel, ou simplement de sortir des tickets Jira. La bonne nouvelle, c'est que ton profil tech est précieux dans énormément de rôles qui ne sont pas du dev pur — et tes compétences (résolution de problèmes, abstraction, rigueur) ouvrent des portes que tu n'imagines pas.",
        'pain_points': [
            "Distance avec le résultat final",
            "Sur-spécialisation technique vs envie de transversal",
            "Solitude relative du métier",
            "Routine des sprints",
        ],
        'alt_paths': [
            {'name': 'Product Manager / Product Owner', 'why': "tu pilotes le quoi et pourquoi, pas que le comment"},
            {'name': 'Tech Lead / Engineering Manager', 'why': "tu encadres et structures au lieu de coder seul"},
            {'name': 'DevRel / Developer Advocate', 'why': "tu parles tech aux humains, pas aux machines"},
            {'name': 'Indépendant·e / freelance senior', 'why': "tu choisis tes projets et ton rythme"},
        ],
        'stat': "Le marché du développement en France comptait plus de 50 000 offres ouvertes en 2025 — la mobilité est plus facile que jamais (source : APEC, 2025).",
        'cta_hook': "Échange 5 min avec Claire pour découvrir 3 pistes alignées avec ce que tu cherches vraiment.",
    },
    'rh': {
        'slug': 'rh',
        'name': 'RH',
        'name_singulier_h': 'un·e RH',
        'h1': 'RH en reconversion : retrouver du sens et de l\'impact',
        'meta_description': "RH qui veut changer de métier ? 5 min pour 3 pistes carrière concrètes adaptées à ton profil et au marché de l'emploi. Gratuit.",
        'intro': "Les RH sont aux premières loges des reconversions des autres — et finissent souvent par envisager la leur. Charge administrative croissante, sentiment d'être tiraillé·e entre direction et salariés, lassitude des procédures. Pourtant ta connaissance fine du facteur humain en entreprise et ta capacité à mener des conversations difficiles sont des atouts rares dans des métiers à fort impact relationnel.",
        'pain_points': [
            "Charge administrative qui prend le pas sur l'humain",
            "Conflits de loyauté direction / salariés",
            "Lassitude des process disciplinaires",
            "Manque de reconnaissance",
        ],
        'alt_paths': [
            {'name': 'Coach professionnel·le', 'why': "tu accompagnes individuellement au lieu de gérer collectivement"},
            {'name': 'Talent acquisition spécialisé', 'why': "tu te recentres sur le recrutement avec moins d'admin"},
            {'name': 'Conseil RH indépendant', 'why': "tu choisis tes missions et ton rythme"},
            {'name': 'Responsable ESS / mission', 'why': "tu mets l'humain au centre dans une structure à impact"},
        ],
        'stat': "Plus de 25% des RH envisagent une reconversion vers le coaching ou le conseil après 8 ans dans le métier (source : ANDRH, 2024).",
        'cta_hook': "5 minutes avec Claire pour identifier les pistes qui correspondent à ce que tu sais déjà très bien faire — autrement.",
    },
    'comptable': {
        'slug': 'comptable',
        'name': 'comptable',
        'name_singulier_h': 'un·e comptable',
        'h1': 'Comptable : 3 pistes carrière au-delà des chiffres',
        'meta_description': "Tu es comptable et tu cherches du nouveau ? 5 min pour 3 pistes adaptées à ton profil et au marché. Gratuit, confidentiel.",
        'intro': "La compta est un métier exigeant, rigoureux, mais qui peut devenir mécanique avec les années. Saisons fiscales qui se ressemblent, automatisation qui change le métier, sentiment de répétition. Ta capacité à traiter de la donnée, à respecter des règles complexes et à voir une organisation par ses flux financiers est un socle énorme — qui ouvre des métiers bien au-delà de la comptabilité pure.",
        'pain_points': [
            "Routine des cycles comptables",
            "Automatisation qui appauvrit le poste",
            "Manque de relationnel",
            "Stress des clôtures",
        ],
        'alt_paths': [
            {'name': 'Contrôle de gestion / FP&A', 'why': "tu passes du backward au forward, plus stratégique"},
            {'name': 'Conseil financier indépendant', 'why': "tu accompagnes les TPE/PME au lieu de les saisir"},
            {'name': 'Formateur·rice comptabilité', 'why': "tu transmets ton savoir et sors du quotidien"},
            {'name': 'Auditeur·rice junior à mid', 'why': "tu varies les contextes et entreprises"},
        ],
        'stat': "Le contrôle de gestion est l'une des évolutions les plus naturelles, avec 40% des reconversions internes des comptables (source : Cabinet Robert Half, 2024).",
        'cta_hook': "Discute 5 min avec Claire et reçois 3 pistes concrètes qui valorisent ta culture chiffres autrement.",
    },
    'professeur': {
        'slug': 'professeur',
        'name': 'enseignant·e',
        'name_singulier_h': 'un·e enseignant·e',
        'h1': 'Enseignant·e en reconversion : valoriser tes compétences ailleurs',
        'meta_description': "Enseignant·e qui veut changer ? 5 min pour 3 pistes carrière concrètes basées sur tes vraies compétences. Gratuit, confidentiel.",
        'intro': "L'enseignement est l'un des métiers les plus exigeants psychologiquement — et l'un des plus mal reconnus financièrement. Charge mentale, gestion de classes difficiles, isolement institutionnel, salaire qui n'évolue pas : la reconversion est un sujet central pour les profs. Et tes compétences (pédagogie, prise de parole, structuration de contenus, gestion de groupes) sont demandées dans énormément d'entreprises.",
        'pain_points': [
            "Salaires qui n'évoluent plus",
            "Charge mentale et émotionnelle",
            "Isolement administratif",
            "Manque de perspectives d'évolution",
        ],
        'alt_paths': [
            {'name': 'Formateur·rice en entreprise', 'why': "tu enseignes dans un cadre adulte mieux rémunéré"},
            {'name': 'Ingénieur·e pédagogique', 'why': "tu conçois les parcours sans les animer toi-même"},
            {'name': 'Consultant·e EdTech', 'why': "tu apportes ton expertise terrain à des startups"},
            {'name': 'Reconversion communication / contenu', 'why': "tu maîtrises déjà la pédagogie et l'écrit"},
        ],
        'stat': "Près de 30 000 enseignants·es démissionnent chaque année en France pour se reconvertir (source : DEPP, ministère de l'Éducation, 2024).",
        'cta_hook': "5 minutes avec Claire pour découvrir 3 pistes où tes années de pédagogie deviennent un vrai atout salarial.",
    },
    'infirmier': {
        'slug': 'infirmier',
        'name': 'infirmier·ère',
        'name_singulier_h': 'un·e infirmier·ère',
        'h1': 'Infirmier·ère épuisé·e : par où commencer ta reconversion ?',
        'meta_description': "Infirmier·ère en reconversion ? 5 min pour 3 pistes adaptées à ton profil soignant et au marché de l'emploi. Gratuit.",
        'intro': "Les infirmiers·ères vivent une des plus fortes vagues de reconversion en France. Burn-out, conditions de travail, salaire vs responsabilité, sentiment d'abandon institutionnel : les raisons sont multiples et profondes. Pourtant tes compétences (résistance au stress, prise de décision rapide, écoute, expertise médicale) ouvrent des chemins très variés, parfois loin du soin classique.",
        'pain_points': [
            "Conditions de travail dégradées",
            "Burn-out fréquent",
            "Manque de reconnaissance financière",
            "Hiérarchie institutionnelle pesante",
        ],
        'alt_paths': [
            {'name': 'Coordinateur·rice de soins', 'why': "tu sors du soin direct mais tu restes dans l'univers"},
            {'name': 'Délégué·e médical·e / pharma', 'why': "tu valorises ton expertise médicale dans le privé"},
            {'name': 'Formateur·rice IFSI / santé', 'why': "tu transmets ton expérience aux nouvelles générations"},
            {'name': 'Naturopathe / coach santé', 'why': "tu reprends le contrôle de ton temps et de tes patients"},
        ],
        'stat': "Plus de 1 infirmier·ère sur 4 envisage de quitter la profession dans les 3 ans (source : Ordre national des infirmiers, 2024).",
        'cta_hook': "Discute 5 min avec Claire et explore 3 pistes concrètes — sans culpabilité, sans pression.",
    },
    'consultant': {
        'slug': 'consultant',
        'name': 'consultant·e',
        'name_singulier_h': 'un·e consultant·e',
        'h1': 'Consultant·e qui veut sortir du conseil : 3 pistes concrètes',
        'meta_description': "Tu es consultant·e et tu veux passer à autre chose ? 5 min pour 3 pistes carrière adaptées à ton profil. Gratuit, confidentiel.",
        'intro': "Le conseil forme bien et paye correctement, mais use vite. Heures interminables, déplacements permanents, distance émotionnelle avec les sujets, sentiment de produire des PowerPoints sans impact. Beaucoup de consultants·es passent en interne ou se réorientent après 3 à 7 ans. Tes compétences (synthèse, structuration, communication exécutive, gestion de complexité) sont parmi les plus transférables qui existent.",
        'pain_points': [
            "Heures de travail extrêmes",
            "Déplacements clients permanents",
            "Distance avec l'impact réel",
            "Standardisation des livrables",
        ],
        'alt_paths': [
            {'name': 'Stratégie / corporate dev en entreprise', 'why': "tu fais du conseil mais en interne, sur un seul sujet long"},
            {'name': 'Product Manager senior', 'why': "tu construis au lieu de recommander"},
            {'name': 'Indépendant·e niche', 'why': "tu choisis tes clients et tes sujets"},
            {'name': 'Investisseur·euse / VC', 'why': "tu transformes l'analyse en pari long-terme"},
        ],
        'stat': "L'attrition annuelle en cabinet de conseil dépasse 20% en France, principalement des juniors et mid-levels en quête de plus de sens (source : Consultor, 2024).",
        'cta_hook': "5 minutes avec Claire pour transformer ton expérience conseil en 3 pistes concrètes hors PowerPoint.",
    },
    'chef-de-projet': {
        'slug': 'chef-de-projet',
        'name': 'chef·fe de projet',
        'name_singulier_h': 'un·e chef·fe de projet',
        'h1': 'Chef·fe de projet en quête de sens : par où commencer ?',
        'meta_description': "Chef·fe de projet qui veut changer ? 5 min pour 3 pistes carrière concrètes adaptées à ton profil et au marché. Gratuit.",
        'intro': "Chef·fe de projet est l'un des profils les plus polyvalents — et donc l'un des plus à même de pivoter. Tu pilotes, tu coordonnes, tu structures, tu communiques avec tous les niveaux. Mais ce rôle d'exécution peut devenir épuisant : tu portes la pression de tout le monde sans avoir toujours la décision. Bonne nouvelle, ces compétences ouvrent des rôles plus stratégiques ou plus créatifs selon ce qui t'attire vraiment.",
        'pain_points': [
            "Pression d'exécution sans pouvoir de décision",
            "Sur-réunions",
            "Sentiment d'être un·e exécutant·e",
            "Multiplicité de sujets non maîtrisés en profondeur",
        ],
        'alt_paths': [
            {'name': 'Product Manager / Product Owner', 'why': "tu passes du suivi au design produit"},
            {'name': 'COO / Operations Manager', 'why': "tu structures l'organisation entière"},
            {'name': 'Indépendant·e / freelance management', 'why': "tu choisis tes missions et ton rythme"},
            {'name': 'Coach agile / scrum master senior', 'why': "tu transmets ta méthode au lieu d'exécuter"},
        ],
        'stat': "Les profils Project Manager avec 5+ ans d'XP sont parmi les plus mobiles, avec 35% qui pivotent vers des rôles produit ou ops (source : LinkedIn Workforce Insights, 2024).",
        'cta_hook': "Discute 5 min avec Claire et découvre 3 pistes pour valoriser ton pilotage autrement.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# VILLES — Top 10 bassins d'emploi en France
# ─────────────────────────────────────────────────────────────────────────────

VILLES = {
    'paris': {
        'slug': 'paris',
        'name': 'Paris',
        'region': 'Île-de-France',
        'h1': "Reconversion professionnelle à Paris : par où commencer ?",
        'meta_description': "Reconversion à Paris : découvre 3 pistes carrière concrètes adaptées au marché parisien en 5 min. Gratuit et confidentiel.",
        'intro': "Paris concentre la plus grande densité d'opportunités professionnelles de France, mais aussi le plus de fatigue, de coûts et de pression. Si tu envisages une reconversion à Paris, l'écosystème est dense (tech, finance, médias, ESS, conseil) et la mobilité interne est plus rapide qu'ailleurs. Le défi est moins de trouver des opportunités que de choisir celles qui te correspondent vraiment.",
        'top_secteurs': ['Tech & startups', 'Finance & conseil', 'Médias & communication', 'ESS & impact'],
        'context': "Avec plus de 6 millions d'actifs dans la région, Paris offre la plus grande variété de secteurs en reconversion. Les bassins tech, ESS et formation continue y sont particulièrement actifs.",
    },
    'lyon': {
        'slug': 'lyon',
        'name': 'Lyon',
        'region': 'Auvergne-Rhône-Alpes',
        'h1': "Reconversion professionnelle à Lyon : 3 pistes adaptées",
        'meta_description': "Reconversion à Lyon : 3 pistes carrière concrètes basées sur le marché local en 5 min de conversation. Gratuit, confidentiel.",
        'intro': "Lyon offre l'un des bassins d'emploi les plus équilibrés de France : à la fois métropole économique majeure et qualité de vie supérieure à Paris. Tech, pharma, finance, industrie : la diversité sectorielle permet une reconversion sans déménager. La concurrence est moins rude qu'à Paris pour les profils expérimentés.",
        'top_secteurs': ['Tech & numérique', 'Pharma & santé', 'Industrie', 'Banque & finance'],
        'context': "Lyon est la 2e métropole économique française. Le bassin de l'emploi représente plus de 1,3 million d'actifs avec une attractivité forte sur les profils tech et ESS.",
    },
    'marseille': {
        'slug': 'marseille',
        'name': 'Marseille',
        'region': 'Provence-Alpes-Côte d\'Azur',
        'h1': "Reconversion professionnelle à Marseille : explorer les pistes locales",
        'meta_description': "Reconversion à Marseille : 3 pistes carrière concrètes basées sur le bassin marseillais en 5 min. Gratuit, confidentiel.",
        'intro': "Marseille est en pleine transformation économique, avec un dynamisme nouveau autour du numérique, du maritime et des industries culturelles. La ville reste plus accessible (logement, qualité de vie) que Paris ou Lyon, ce qui en fait une destination de plus en plus prisée pour les reconversions venues d'ailleurs.",
        'top_secteurs': ['Numérique & startups', 'Maritime & logistique', 'Industries culturelles', 'Santé'],
        'context': "Le grand Marseille connaît une croissance significative dans les secteurs tech et créatifs depuis 2020, portée par l'investissement public et privé.",
    },
    'toulouse': {
        'slug': 'toulouse',
        'name': 'Toulouse',
        'region': 'Occitanie',
        'h1': "Reconversion professionnelle à Toulouse : 3 pistes ciblées",
        'meta_description': "Reconversion à Toulouse : 3 pistes carrière concrètes adaptées au bassin local en 5 min. Gratuit, confidentiel.",
        'intro': "Toulouse vit au rythme de l'aéronautique, mais le bassin se diversifie rapidement vers la tech, le médical et l'agroalimentaire. C'est une ville idéale pour les profils ingénieurs en reconversion qui veulent rester dans un univers technique tout en pivotant vers d'autres secteurs.",
        'top_secteurs': ['Aéronautique & spatial', 'Tech & numérique', 'Santé & médical', 'Agroalimentaire'],
        'context': "Le bassin toulousain rassemble plus de 600 000 actifs avec une concentration unique en France sur l'aéronautique et l'industrie de pointe.",
    },
    'bordeaux': {
        'slug': 'bordeaux',
        'name': 'Bordeaux',
        'region': 'Nouvelle-Aquitaine',
        'h1': "Reconversion professionnelle à Bordeaux : par où commencer ?",
        'meta_description': "Reconversion à Bordeaux : 3 pistes carrière adaptées au bassin local en 5 min. Gratuit, confidentiel.",
        'intro': "Bordeaux combine attractivité résidentielle et dynamisme économique en croissance. Au-delà du vin, la ville développe ses pôles tech, design et services. Pour une reconversion, le bassin offre des opportunités plus rares que Paris mais sur des marchés moins saturés — ce qui peut être un avantage net.",
        'top_secteurs': ['Vin & tourisme', 'Tech & numérique', 'Industries créatives', 'Santé'],
        'context': "Bordeaux attire chaque année des milliers de profils en reconversion, particulièrement venus de Paris, séduits par la qualité de vie et un marché de l'emploi en consolidation.",
    },
    'nantes': {
        'slug': 'nantes',
        'name': 'Nantes',
        'region': 'Pays de la Loire',
        'h1': "Reconversion professionnelle à Nantes : 3 pistes adaptées",
        'meta_description': "Reconversion à Nantes : 3 pistes carrière concrètes basées sur le bassin nantais en 5 min. Gratuit, confidentiel.",
        'intro': "Nantes est régulièrement classée parmi les villes les plus dynamiques de France pour l'emploi. Tech, ESS, industries créatives, agroalimentaire : le bassin se distingue par sa diversité et sa culture entrepreneuriale forte. C'est un terrain particulièrement propice aux reconversions vers l'impact et la créativité.",
        'top_secteurs': ['Tech & numérique', 'ESS & impact', 'Industries créatives', 'Agroalimentaire'],
        'context': "Nantes a un écosystème ESS parmi les plus matures de France et un bassin tech en forte croissance, particulièrement attractif pour les profils en quête de sens.",
    },
    'lille': {
        'slug': 'lille',
        'name': 'Lille',
        'region': 'Hauts-de-France',
        'h1': "Reconversion professionnelle à Lille : explorer les pistes locales",
        'meta_description': "Reconversion à Lille : 3 pistes carrière concrètes adaptées au marché lillois en 5 min. Gratuit, confidentiel.",
        'intro': "Lille bénéficie d'une position stratégique entre Paris, Bruxelles et Londres, et d'un écosystème tech (Euratechnologies) parmi les plus matures de France. La reconversion dans la métropole est particulièrement portée par le numérique, le retail et la formation, avec un coût de la vie nettement inférieur à Paris.",
        'top_secteurs': ['Tech & numérique', 'Retail & e-commerce', 'Industrie', 'Logistique'],
        'context': "Le bassin lillois rassemble plus de 1,2 million d'habitants. L'incubateur Euratechnologies est l'un des plus grands d'Europe et structure l'écosystème tech local.",
    },
    'strasbourg': {
        'slug': 'strasbourg',
        'name': 'Strasbourg',
        'region': 'Grand Est',
        'h1': "Reconversion professionnelle à Strasbourg : 3 pistes concrètes",
        'meta_description': "Reconversion à Strasbourg : 3 pistes carrière adaptées au bassin local en 5 min. Gratuit, confidentiel.",
        'intro': "Strasbourg est un carrefour européen unique en France, avec une économie portée par les institutions européennes, la pharma, la finance et l'artisanat haut de gamme. Pour une reconversion, le bassin est plus restreint que les grandes métropoles mais offre des opportunités spécifiques sur des secteurs internationaux.",
        'top_secteurs': ['Pharma & santé', 'Institutions européennes', 'Finance', 'Artisanat & luxe'],
        'context': "Strasbourg accueille plus de 25 institutions européennes et internationales. Le bassin reste l'un des plus internationaux de France hors Île-de-France.",
    },
    'montpellier': {
        'slug': 'montpellier',
        'name': 'Montpellier',
        'region': 'Occitanie',
        'h1': "Reconversion professionnelle à Montpellier : par où commencer ?",
        'meta_description': "Reconversion à Montpellier : 3 pistes carrière adaptées au marché local en 5 min. Gratuit, confidentiel.",
        'intro': "Montpellier est l'une des villes les plus dynamiques démographiquement et économiquement de France. Numérique, santé, recherche : la ville attire les profils qui cherchent à allier reconversion et qualité de vie méditerranéenne. Le marché est en consolidation, donc plus accessible qu'à Paris ou Lyon pour les profils expérimentés.",
        'top_secteurs': ['Tech & numérique', 'Santé & biotech', 'Recherche', 'Tourisme'],
        'context': "Montpellier connaît une croissance démographique parmi les plus fortes de France. Le pôle French Tech local est très actif sur les sujets santé et environnement.",
    },
    'nice': {
        'slug': 'nice',
        'name': 'Nice',
        'region': 'Provence-Alpes-Côte d\'Azur',
        'h1': "Reconversion professionnelle à Nice : 3 pistes ciblées",
        'meta_description': "Reconversion à Nice : 3 pistes carrière adaptées au bassin local en 5 min. Gratuit, confidentiel.",
        'intro': "Nice et la Côte d'Azur offrent un mix unique entre tourisme, tech (Sophia Antipolis), industries créatives et internationalité. Pour une reconversion, le bassin est plus restreint que les grandes métropoles mais permet souvent de combiner projet professionnel et qualité de vie spécifique au littoral méditerranéen.",
        'top_secteurs': ['Tourisme & hôtellerie', 'Tech & Sophia Antipolis', 'Industries créatives', 'Yachting & luxe'],
        'context': "Le bassin Nice / Sophia Antipolis est l'un des plus grands clusters tech de France hors Île-de-France, avec plus de 35 000 emplois technologiques.",
    },
}
