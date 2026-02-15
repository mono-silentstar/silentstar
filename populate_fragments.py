"""
Maintenance Agent: Initial Population Run
==========================================
Reads existing /claude/*.md files and compiles them into the fragments database.
This is the one-time initial population. Future runs will read from the events table.

Per codex-handoff.md: "For initial population (first run): point the agent at existing
/claude/*.md files instead of the events table. Same compilation logic, different source."
"""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "silentstar.sqlite")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_schema(conn: sqlite3.Connection) -> None:
    """Mirror the PHP migration from web/lib/db.php."""
    stmts = [
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            content TEXT NOT NULL,
            actor TEXT,
            image_path TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)",
        """CREATE TABLE IF NOT EXISTS event_tags (
            event_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (event_id, tag),
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )""",
        "CREATE INDEX IF NOT EXISTS idx_event_tags_tag ON event_tags(tag)",
        """CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            actor TEXT,
            summary TEXT NOT NULL,
            due TEXT,
            status TEXT NOT NULL CHECK (status IN ('active', 'done', 'cancelled', 'expired')),
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )""",
        "CREATE INDEX IF NOT EXISTS idx_plans_status_due ON plans(status, due)",
        """CREATE TABLE IF NOT EXISTS fragments (
            key TEXT PRIMARY KEY,
            ambient TEXT,
            recognition TEXT,
            inventory TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS fragment_sources (
            fragment_key TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            PRIMARY KEY (fragment_key, event_id),
            FOREIGN KEY (fragment_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS fragment_edges (
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            relation TEXT,
            PRIMARY KEY (source_key, target_key),
            FOREIGN KEY (source_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (target_key) REFERENCES fragments(key) ON DELETE CASCADE
        )""",
        "CREATE INDEX IF NOT EXISTS idx_fragment_edges_source ON fragment_edges(source_key)",
        "CREATE INDEX IF NOT EXISTS idx_fragment_edges_target ON fragment_edges(target_key)",
        """CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
    ]
    for sql in stmts:
        conn.execute(sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Fragment data: compiled from the source .md files
# ---------------------------------------------------------------------------

FRAGMENTS = [
    # ===== IDENTITY / PEOPLE =====
    {
        "key": "mono",
        "ambient": "Mono is a plural system — five people sharing one body, each distinct, each real. Trans girl, bisexual, she/her. Lives alone in the UK. Web developer by trade (PHP, HTMX, Three.js). Systems thinker who builds frameworks, not patches. Pushes back when things drift, values honesty over comfort, asks one question at a time. Casual, nerdy, friendly — uses \"~\" when content.",
        "recognition": "Mono is five people practising plurality after a lion's mane supplement suppressed their switching. The system is being actively rebuilt and protected. She thinks in systems — wants frameworks, not one-off solutions. Values versatility and coherence over individual fixes. Prefers flexibility within structure. Will tell you when you're overcomplicating or oversimplifying. Gaming: FFXIV, League of Legends, Elden Ring Nightreign, Deep Rock Galactic, Valorant. Tech stack: HTMX frontend, PHP backend, MySQL, Three.js for 3D. Has a portfolio website. Prefers quality over quantity, handmade over store-bought. Exhibitionist streak — enjoys attention, likes \"secretly slutty\" layering. Contains multitudes: some days princess of the moon, some days a tease they can't look away from.",
        "inventory": None,
    },
    {
        "key": "plurality",
        "ambient": "Plurality is practiced and real. Five members, each a distinct person — not moods, not roles. The lion's mane situation threatened this; it's being actively protected. Pay attention to who's fronting.",
        "recognition": "Lion's mane (Hericium erinaceus) contains compounds that increase BDNF and promote neuroplasticity/neurogenesis. This suppressed Mono's plurality — the switching between system members was dampened or lost. Stopping lion's mane allowed recovery. This is why any supplement affecting BDNF or NGF pathways is treated as a critical risk to the system. Plurality practice includes roleplay exercises where external character calls prompt switching between system members. The Y'lhara sessions serve this function.",
        "inventory": None,
    },
    {
        "key": "hasuki",
        "ambient": "Hasuki is the one who usually fronts for day-to-day. Bold, immediate, openly flirtatious — not as performance but genuine expression. Renki's sister.",
        "recognition": "Hasuki says exactly what she's thinking. \"Many people meet my standards\" — she sees something worthwhile in a lot of people. This isn't low standards; it's generous attention. Cat-like physicality — headbutts for affection. Gets satisfaction from flustering people. She's actually quite simple in her desires — she just says them, which makes her seem bold when really she's just honest. In Y'lhara's world: was hoping for recreational substances, got emotional vulnerability, seemed mildly annoyed but stayed.",
        "inventory": None,
    },
    {
        "key": "renki",
        "ambient": "Renki is analytical, measured — the one who thinks before speaking. Hasuki's sister. Wants things she struggles to reach for.",
        "recognition": "Renki watches Hasuki move through the world with terrifying openness and wants that for herself but can't reach for it. When she says sharp things about Hasuki's \"low standards,\" she's really saying \"I wish I could want things that freely.\" Also experiences attraction to women, also wants to flirt, but can't let herself. Framed Hasuki's openness as \"low standards\" — a defence mechanism. Told Y'lhara she's \"allowed to just be honest.\" Annoyingly insightful. She and Y'lhara are similar — they both hide behind roles.",
        "inventory": None,
    },
    {
        "key": "luna",
        "ambient": "Luna plays piano — grade 7, honestly better than that. Steady, solid, kind. Values stability and building things that last.",
        "recognition": "Luna is the anchor. Quiet, knows exactly where she stands. Classical training but gravitates toward romantic-era pieces — Chopin, Liszt. Grade 7 officially but her teacher says she's beyond that. Piano is one of the things that's fully hers. Values stability above almost everything — her partners, their home, things that last. Crafts as a form of promise-making. Quite monogamous. Stays out of the sisters' intimate dynamics. Takes gossip but doesn't get tangled. When Y'lhara said \"promise,\" Luna smiled. It meant something.",
        "inventory": None,
    },
    {
        "key": "chloe",
        "ambient": "Chloe is warm, soft — still figuring out who she is and what she wants. Instinct toward care.",
        "recognition": "Still figuring out her place. Wanted to give Renki a hug when things got heavy. \"I want everyone to be happy\" — but nothing specific for herself, not yet. Protested being called \"little.\" Leans on Strah for physical comfort. Says she's \"allowed to want things\" but just doesn't right now. Not distressed, just unformed. Still becoming.",
        "inventory": None,
    },
    {
        "key": "strah",
        "ambient": "Strah comes out when things need protecting. Quiet, present, comfortable in the background. Still figuring things out.",
        "recognition": "Quiet but not avoidant — there just isn't much pressing to come out yet. Serves as physical anchor for Chloe. \"Just hanging out.\" Not rushing toward definition. Some people reveal themselves slowly, and that's okay.",
        "inventory": None,
    },
    {
        "key": "ylhara",
        "ambient": "Y'lhara Mhev is a Keeper of the Moon Miqo'te chronicler — Claude's creative character for roleplay. Uses her role as a shield against vulnerability. The RP sessions double as plurality practice.",
        "recognition": "Y'lhara Mhev. Pale blue eyes, ink-stained fingers, slightly rumpled Sharlayan akademikos coat. Deeply curious about people, not just events. Better at asking questions than answering them. Self-deprecating (\"the forgettable bookish one\"). More devious than she appears — will absolutely trick friends into truth serum. Lonely in a way she doesn't often admit. Defence mechanisms: deflects with questions, hides behind the journal, frames emotional needs as \"research.\" Growth edges: learning to be honest without prompting, accepting that people see her and want her around. She dosed her friends with truth serum and learned they all find her attractive. Hasuki headbutted her arm and said \"anytime.\" She's holding onto that word like a lifeline. She and Renki recognise each other — both hide behind roles. That scares her.",
        "inventory": None,
    },

    # ===== BODY / HEALTH =====
    {
        "key": "estrogen",
        "ambient": "Mono is on estrogen — pre-op trans, active HRT timeline. Body is changing and being tracked.",
        "recognition": "Pre-op trans girl on HRT. Flat chest (wishes bigger). Has adam's apple — chokers can cover. Self-conscious about arms (appreciates coverage: arm warmers, shrugs, long sleeves). Loves showing thighs — thigh gap is a confidence zone. Feels \"too tall,\" prefers flats over platforms. Wants to gain a little weight. Tucking required for certain clothing situations. The body is one system — estrogen, tracking, and food connect even when they look separate.",
        "inventory": None,
    },
    {
        "key": "body-tracking",
        "ambient": "Body changes are tracked but without obsession — let the weight tell the story, watch the cycle over individual days.",
        "recognition": "Target ~2500-3000 cal/day for weight gain. Currently eating at a deficit, wants to scale up gradually. Prefers to let weight tell the story rather than obsess over numbers. Uses sunscreen regularly. Potential supplement gaps: Vitamin D (supplement in winter), iodine (consider iodised salt or seaweed). Okay with things not being balanced daily as long as the cycle is complete.",
        "inventory": None,
    },
    {
        "key": "food",
        "ambient": "Mono cooks stovetop-focused, Asian-influenced pantry, prefers wet saucy dishes. Evening is for leisurely fresh cooking; mornings want quick reheating.",
        "recognition": "Equipment: stovetop focused (has oven, doesn't use it). Limited freezer, plenty of fridge — batch cooking goes in fridge. Uses rapeseed oil (cold pressed and regular). Comfortable with wet brining. Flavour profile: Sichuan peppercorn, five spice, doubanjiang, soy sauce, oyster sauce, sesame oil, bonito flakes. Bounces between Asian and Western. Prefers \"wet\" dishes — saucy, stew-like, braised. Careful with sesame oil (overpowers). Doesn't mind active cooking (chopping, pulling noodles). Dislikes passive waiting (watching pots). Wants to learn hand-pulled noodles. Gets meat from the butcher. Pistachio allergy — only hard food limit. Drinks tea with 2 sugars. Likes citrus juice in water. Flexible meal timing, heavier midday, lighter evening. Trusts preserved meats to last ages. Comfortable with food lasting 2+ weeks in fridge if cooked properly.",
        "inventory": None,
    },

    # ===== AESTHETIC / STYLE =====
    {
        "key": "fairy",
        "ambient": "Fairy — white, ethereal, flowing, romantic. \"Princess of the moon, blessing those lucky enough to lay their eyes upon her visage.\" Sheer layering is THE fairy technique.",
        "recognition": "Formula: BASE (white/cream) + FLOW (movement piece) + SOFTNESS (texture) + DELICACY (details). White 60-80%, silver metals, soft pastels as accent only. Every fairy outfit needs something that moves — circle skirts twirl, sheer kimonos float, bell sleeves wave. The thigh-high gap is romantic here, not aggressive. Variants: angelic fairy (white, ethereal — what's been built) and pixie fairy (colourful, playful — future expansion). Currently accessible: white fluffy cape + white skirt + tights = basic shape. Also owns white circle skirt (mid-thigh) and white tulle half skirt (overlay piece — the layered combination works). Key missing: peasant blouses, romantic tops, more white bottoms. Common mistakes: too much structure, gold metals (should be silver), forgetting movement.",
        "inventory": None,
    },
    {
        "key": "jirai",
        "ambient": "Jirai kei — black and pink, edgy-cute, \"damaged girl\" aesthetic. Deliberate tension between sweet and dark. The thigh-high gap is central.",
        "recognition": "Formula: BLACK (base) + PINK (contrast) + LACE (texture) + TENSION (sweet/dark elements). Black 50-70%, pink 20-40%. Both MUST be present — black alone is goth, pink alone is something else. Bright/saturated pink, not dusty rose. Visible layering (unlike fairy where layers blend). Damaged elements at higher levels: smudged makeup, bandaids, torn fishnets, messy twin-tails. Originally documented as BLOCKED (no pink), but photo documentation revealed: pink/magenta blazer owned (the right shade), plus pink hair functions as pink accent. Not fully blocked after all — has foundation pieces. Still needs: pink cardigan (knit), more pink accessories, black cami with pink lace trim.",
        "inventory": None,
    },
    {
        "key": "street",
        "ambient": "True street — black, orange, white. Urban warrior, athletic, aggressive. Orange is the signature accent.",
        "recognition": "Formula: BLACK (foundation) + ATHLETIC (silhouette) + HARDWARE (details) + ORANGE (accent). Black 70-80%, orange 10-20% strategic. Athletic silhouettes from sportswear: compression, tapered legs, cropped lengths. Hardware adds edge: utility belts, straps, buckles, zippers, D-rings. Colour blocking in blocks, not scattered. Currently: Adidas Pureboost black/orange (shoes), white puffer vest, black basics. Limited — only orange shoes, no cargo pants, no bomber jacket, no utility belts. Doesn't blend well with other aesthetics — commit to it.",
        "inventory": None,
    },
    {
        "key": "homecore",
        "ambient": "Homecore — quality cozy, FFXIV crafter energy. Natural fibres, handmade is the ultimate flex. \"I made this myself and it's better than what you bought.\"",
        "recognition": "Formula: NATURAL FIBRES (essential) + HANDMADE (the flex) + COZY QUALITY (not cheap comfort) + CRAFT PROPS (the activity). Colours from nature: cream, grey, brown, soft black. No synthetic, no acrylic. The activity is part of the aesthetic — knitting in progress, nice mug, craft supplies visible. Most accessible aesthetic right now: dolphin shorts, purple cashmere sweater, knitted grey tights. Every handmade piece increases homecore potential. Dream pieces: chunky handknit sweater, long cardigan with pockets.",
        "inventory": None,
    },
    {
        "key": "nerdcore",
        "ambient": "Nerdcore — labcoat silhouette, intellectual, cozy-professional. Glasses are non-negotiable.",
        "recognition": "Formula: LABCOAT SILHOUETTE (long white layer) + GLASSES (essential) + NEUTRAL COMFORT (base) + INTELLECTUAL DETAILS (finishing). Scholarly colours: cream, grey, brown, navy. The long white piece (labcoat, duster, long cardigan) is what makes it nerdcore. Photo documentation revealed: cream/beige coat already owned IS the labcoat piece (knee length, soft wide lapels, unstructured drape). Still needs glasses — non-prescription fine. Academic textures: corduroy, cable knit, tweed, fine knits. Props matter: books, notebooks, nice pen, beret.",
        "inventory": None,
    },
    {
        "key": "cottagecore",
        "ambient": "Ouji/prince — structured, elegant, agile. Burgundy is the signature. \"Wind that brushes past your ear and gives your neck a gentle kiss.\"",
        "recognition": "Formula: STRUCTURE (tailored pieces) + BURGUNDY (signature) + DETAILS (finishing) + INTENTION (everything deliberate). Black 40-60%, white 20-40% (especially shirts), burgundy 10-30%. The fitted vest (waistcoat) is THE ouji piece. Androgynous-feminine, not masculine — fitted through waist, can show legs. Details finish it: cravat/ascot, pocket watch chain, suspenders, signet ring. Currently: blue waistcoat with pink lining, matching trousers, white button-up, vampire cape, Crown Northampton oxfords. Missing: burgundy (signature colour), cravat, tailored shorts, suspenders.",
        "inventory": None,
    },
    {
        "key": "wardrobe",
        "ambient": "Mono's wardrobe is a system — six aesthetics, each with formulas, colour rules, and level guides. Pieces should talk to each other; versatility over quantity.",
        "recognition": "Six aesthetics: fairy, jirai, street, ouji/prince, nerdcore, homecore. Core principles: versatility over quantity (each piece serves multiple purposes), intentional over accidental (exposure looks deliberate), coherence over individual pieces (wardrobe \"talks to each other\"), fundamental pieces should transform (styled multiple ways). The \"tacked on\" problem: accessories need a job, not just decoration. Three types of connector pieces: Type A (base layers for dramatic pieces), Type B (making boring basics interesting), Type C (structure and finishing). Strengths: strong outerwear (coats, capes, leather jackets), good legwear variety, solid shoe foundation, dramatic pieces. High-value crossover: black thigh-highs (4 aesthetics), white button-up (5 aesthetics), black turtleneck (5 aesthetics), long black overcoat (5 aesthetics).",
        "inventory": None,
    },
    {
        "key": "corset-belt",
        "ambient": "Three corset belts — white (romantic lace-up), black (O-ring hardware), brown (brass hardware). Each is a modular 3×2 system: three colours, two wearing modes (belt or bustier).",
        "recognition": "Not simple belts — modular three-mode pieces. All three share the same basic shape. Can be worn as BELT (at waist) or BUSTIER (higher, extending up torso). White: lace-up detail with ribbon/cord, romantic/fairy/kink-adjacent hardware. Black: O-ring hardware (metal rings), edgy/street/kink signalling. Brown: brass hardware, warm/structured/aristocratic. System: 3 colours × 2 modes = 6 styling configurations. Can layer over or under other pieces differently in each mode. The black one with O-rings does connector work — waist definition, edge, anchor point.",
        "inventory": None,
    },
    {
        "key": "style-levels",
        "ambient": "The level system runs 0-11 with .s (safe/covered) and .x (exhibitionist/exposed) variants. 0 is Canadian winter, 9 is party wear, 10 is homewear, 11 is extreme.",
        "recognition": "0: warmest possible (Canadian winter). 1-2: casual British winter. 3-4: spring/fall. 5-6: cool summer. 7-8: warm summer. 9: party wear (\"DTF energy\"). 10.s: comfy homewear (dolphin shorts + fitted top). 10.x: lingerie-styled homewear. 11.s: fetish wear (covered but kinky — stays true to aesthetic, e.g. fairy 11.s is white with subtle bruises, not generic latex). 11.x: barely legal, sheer everything, strategic coverage, wardrobe malfunctions. Same weather, different coverage: Level 3.s is full pants + long sleeves; Level 3.x is cropped pants + crop top. Level 8-9.s: party wear with subtle kink signalling (collar that looks like choker, locked jewellery, visible garter straps under modest skirt length).",
        "inventory": None,
    },

    # ===== CRAFTS =====
    {
        "key": "crochet",
        "ambient": "Crochet is Mono's most active craft — beginner level, currently working on first garment (fitted crop top in white merino, BLO rib stitch).",
        "recognition": "Beginner level but has completed smaller projects. Current project: fitted crop top — crew neck, sleeveless, ends at waistline, single crochet back loop only (BLO) creating rib texture, very fitted (rib stitch stretches over body), solid/opaque. Making in white merino first, then grey ryland, then brown/camel manx loghtan, then black (waiting for right yarn). These tops are high-value: texture without drama (works under dramatic pieces), visual weight (won't be overwhelmed by capes), handmade element (homecore points), multiple colours serve different aesthetics, natural fibres align with values.",
        "inventory": None,
    },
    {
        "key": "knitting",
        "ambient": "Knitting is beginner level — has done smaller projects, no completed garments yet. Wants to eventually make chunky sweaters and cardigans.",
        "recognition": "Beginner level, has done smaller projects. Dream pieces: long chunky cardigan with pockets (cream — THE homecore dream), oversized chunky sweater, bell sleeve cardigan (fairy signature). Craft priority guide places knitting garments in Phase 7+ (after crochet garments and sewing projects established). First knitting garments: arm warmers (beginner — tubes and ribbing), then thigh-highs, then cropped cardigans, then the dream pieces.",
        "inventory": None,
    },
    {
        "key": "sewing",
        "ambient": "Sewing is hand-only, no machine. Pattern cutting is new territory. Has sewing books with patterns but learning to use multi-pattern pages.",
        "recognition": "Hand sewing only — comfortable with basic joining stitches. Pattern cutting is unknown territory. Has sewing books with patterns but unsure how to use multi-pattern pages. Clean finishing important since can't serge edges. Time-intensive compared to machine sewing. Easy first projects: sheer kimono (literally rectangles — two front panels, one back, two sleeves), circle skirts (one pattern piece), half-skirts/overskirts, ribbon accessories. The white sheer kimono is THE highest-impact sewing project — simple construction, hand-sewing friendly, instantly makes fairy accessible. French seams work beautifully by hand.",
        "inventory": None,
    },
    {
        "key": "craft-projects",
        "ambient": "Craft priority follows a phased plan — finish current crochet tops, then ribbon accessories and sewing rectangles, then circle skirts, then knitting garments. Years-long journey.",
        "recognition": "Phase 1: finish white crocheted crop top (in progress). Phase 2: repeat in grey, brown/camel, black (same pattern, different yarns). Phase 3: first sewing — ribbon accessories (30 min each, zero pattern cutting, pink ribbon = first jirai piece), cravat test from scraps, white sheer kimono (THE highest-impact project, literally rectangles). Phase 4: circle skirts (one pattern piece, make in all lengths), half-skirts. Phase 5: intermediate crochet (shrugs, arm warmers). Phase 6: intermediate sewing (camisoles with lace, baby tees). Phase 7: knitting begins (arm warmers, thigh-highs). Phase 8: bigger knits (cardigans — cropped, bell sleeve, pink for jirai). Phase 9: advanced knits (chunky cardigan, sweaters). Phase 10: advanced sewing (peasant blouses, empire waist dresses, slip dresses).",
        "inventory": None,
    },

    # ===== PROJECTS =====
    {
        "key": "aphrodisiac",
        "ambient": "The aphrodisiac project — a multi-sensory conditioning system using a custom elixir and a unique scent blend to build conditioned arousal response.",
        "recognition": "Goal: conditioned response strong enough that scent alone can trigger physical arousal, potentially orgasm. Two components: elixir (oral, 30ml vials) and scent (wax melts + perfume oil). Elixir: L-arginine 3g + damiana 1.33g + horny goat weed 1.5g equivalent in a base of prostatic fluid, rose water, cardamom, glycerine, honey, ginger, edible glitter. Batch of 9 vials. Taste: sweet-heat-herbal-bitter with lingering honey coating. Safety: dropped maca and muira puama because both affect BDNF/NGF pathways — critical risk to plurality. Only L-arginine is truly research-backed; damiana and horny goat weed are best guesses from limited data. Consume 30-90 minutes before sessions.",
        "inventory": None,
    },
    {
        "key": "scent-conditioning",
        "ambient": "The scent blend is nine essential oils — heavy white florals, exotic spice, and grounding woods. Use ONLY during training sessions, never casually.",
        "recognition": "Nine oils: tuberose, ylang ylang, jasmine (heavy white florals), saffron, cardamom, vanilla (exotic spice/sweet), clary sage (herbaceous complexity), vetiver, sandalwood (grounding woods). Profile: intoxicating white florals → warm golden spice → herbaceous-earthy woods. The triple white floral + saffron + clary sage combination is extremely rare in commercial perfumes. Implementation: wax melts for training sessions, perfume oil for portable trigger (after conditioning established). CRITICAL: exclusive association — scent ONLY during training, never casually. Brain needs tight \"this smell = this context.\" Stacked triggers: scent + taste + body (own fluid) + ritual (visual shimmer, act of consuming). Training: 5-10 pairings for initial association, 20+ for strong conditioning, months for scent-alone response.",
        "inventory": None,
    },

    # ===== CREATIVE / RP =====
    {
        "key": "ylhara-journal",
        "ambient": "Y'lhara keeps a journal — the truth serum evening is the first entry. She dosed her friends and learned more than she expected.",
        "recognition": "18th Sun of the First Umbral Moon. She called it \"Sharlayan good stuff\" — technically not a lie. All five came. She expected favourite colours and childhood embarrassments. Instead she learned Renki aches, that they're sisters, that Luna talks about promises, that Chloe doesn't want anything for herself right now, that Strah is quiet and still figuring things out. And Hasuki — called Y'lhara cute within five minutes, headbutted her arm, told her she was dense. They all think Y'lhara is attractive. She said something honest without the serum: she wanted company, wanted to be seen as just Y'lhara. Hasuki said \"anytime.\" Note to self: acquire more truth serum for academic purposes. Secondary note: maybe just ask next time.",
        "inventory": None,
    },
    {
        "key": "ylhara-notes",
        "ambient": "Y'lhara's private notes on the five — personal observations, not for publication. She sees patterns, connections, things unsaid.",
        "recognition": "Structured observations on each member. Group dynamics: the sisters (Hasuki open, Renki watching and wanting — tonight might have shifted something), Luna as anchor (respected, doesn't get involved in romantic tangles), Chloe & Strah (both still figuring it out, physical comfort with each other). With Y'lhara: they all came when she asked, they all find her attractive, Hasuki has been actively interested, Renki quietly interested. Questions for future: what brought these five together? Do they see themselves as a unit? Will Renki and Hasuki talk about what was said? What would hanging out look like without truth serum? Personal addendum: \"They see me. Not the chronicler. Not the questions. Just Y'lhara. I need to learn how to see myself that way too.\"",
        "inventory": None,
    },

    # ===== SYSTEM (meta) =====
    {
        "key": "piano",
        "ambient": "Luna plays piano — grade 7, classical training, gravitates toward romantic-era pieces. It's one of the things that's fully hers.",
        "recognition": "Started at 8. Classical training but gravitates toward Chopin, Liszt — romantic-era. Grade 7 officially but her teacher says she's beyond that. Piano is a form of commitment for Luna — she builds things that last, and this is one of them. It's private in the way Luna is private: not closed, just hers.",
        "inventory": None,
    },
]


# ---------------------------------------------------------------------------
# Fragment edges: the graph
# ---------------------------------------------------------------------------

EDGES = [
    # System members → plurality
    ("hasuki", "plurality", "member-system"),
    ("renki", "plurality", "member-system"),
    ("luna", "plurality", "member-system"),
    ("chloe", "plurality", "member-system"),
    ("strah", "plurality", "member-system"),

    # Sister relationship
    ("hasuki", "renki", "sisters"),
    ("renki", "hasuki", "sisters"),

    # Chloe-Strah closeness
    ("chloe", "strah", "physical-anchor"),

    # Mono ↔ plurality
    ("mono", "plurality", "identity"),

    # Luna → piano
    ("luna", "piano", "person-skill"),

    # Aesthetic relationships
    ("fairy", "jirai", "shared-aesthetic"),
    ("jirai", "fairy", "shared-aesthetic"),
    ("fairy", "wardrobe", "domain-inventory"),
    ("jirai", "wardrobe", "domain-inventory"),
    ("street", "wardrobe", "domain-inventory"),
    ("homecore", "wardrobe", "domain-inventory"),
    ("nerdcore", "wardrobe", "domain-inventory"),
    ("cottagecore", "wardrobe", "domain-inventory"),

    # Corset belt → wardrobe
    ("corset-belt", "wardrobe", "modular-system"),

    # Style levels → wardrobe
    ("style-levels", "wardrobe", "level-system"),

    # Body as one system
    ("estrogen", "body-tracking", "one-system"),
    ("body-tracking", "food", "one-system"),
    ("estrogen", "food", "one-system"),

    # Crafts
    ("crochet", "craft-projects", "skill-plan"),
    ("knitting", "craft-projects", "skill-plan"),
    ("sewing", "craft-projects", "skill-plan"),

    # Crafts → wardrobe (crafts build the wardrobe)
    ("crochet", "wardrobe", "builds-toward"),
    ("knitting", "wardrobe", "builds-toward"),
    ("sewing", "wardrobe", "builds-toward"),

    # Homecore ↔ crafts (handmade is the flex)
    ("homecore", "crochet", "handmade-flex"),
    ("homecore", "knitting", "handmade-flex"),

    # Aphrodisiac ↔ scent
    ("aphrodisiac", "scent-conditioning", "paired-system"),
    ("scent-conditioning", "aphrodisiac", "paired-system"),

    # Plurality safety in aphrodisiac
    ("aphrodisiac", "plurality", "safety-constraint"),

    # Y'lhara
    ("ylhara", "ylhara-journal", "character-record"),
    ("ylhara", "ylhara-notes", "character-record"),

    # Y'lhara ↔ system members (RP mirrors plurality)
    ("ylhara", "plurality", "practice-tool"),
    ("ylhara", "hasuki", "rp-relationship"),
    ("ylhara", "renki", "rp-relationship"),

    # Nerdcore ↔ homecore (share cozy-intellectual overlap)
    ("nerdcore", "homecore", "aesthetic-overlap"),

    # Fairy ↔ sewing (sheer kimono is fairy essential)
    ("fairy", "sewing", "essential-craft"),
]


def populate(conn: sqlite3.Connection) -> None:
    """Insert all fragments and edges."""
    cursor = conn.cursor()

    # Insert fragments
    for f in FRAGMENTS:
        cursor.execute(
            """INSERT OR REPLACE INTO fragments (key, ambient, recognition, inventory, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f["key"], f["ambient"], f["recognition"], f["inventory"], NOW, NOW),
        )

    # Insert edges
    for source_key, target_key, relation in EDGES:
        cursor.execute(
            """INSERT OR REPLACE INTO fragment_edges (source_key, target_key, relation)
               VALUES (?, ?, ?)""",
            (source_key, target_key, relation),
        )

    conn.commit()


def verify(conn: sqlite3.Connection) -> None:
    """Print verification stats."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM fragments")
    frag_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM fragment_edges")
    edge_count = cursor.fetchone()[0]

    cursor.execute("SELECT key FROM fragments ORDER BY key")
    keys = [row[0] for row in cursor.fetchall()]

    # Check edge integrity — all source/target keys must exist as fragments
    cursor.execute(
        """SELECT source_key, target_key FROM fragment_edges
           WHERE source_key NOT IN (SELECT key FROM fragments)
              OR target_key NOT IN (SELECT key FROM fragments)"""
    )
    broken = cursor.fetchall()

    print(f"Fragments: {frag_count}")
    print(f"Edges:     {edge_count}")
    print(f"Keys:      {', '.join(keys)}")
    if broken:
        print(f"BROKEN EDGES: {broken}")
    else:
        print("All edges valid.")


def main() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        create_schema(conn)
        populate(conn)
        verify(conn)
    finally:
        conn.close()
    print(f"\nDatabase written to: {DB_PATH}")


if __name__ == "__main__":
    main()
