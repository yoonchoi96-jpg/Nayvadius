# Daily Briefing Architecture

## Purpose

Daily Briefing is a separate system from Reader first-pass classification. Its job is not to rate documents; it synthesizes already-processed knowledge and answers: **"What do I actually need to know today?"**

## Ownership

- Reader Gemini Gem: first-pass color classification only.
- Abraham: translation, detailed Rating, Entity, Relation, Topic and knowledge extraction.
- Nayvadius: Obsidian normalization, entity unification, deduplication, linking and final knowledge structure.
- Daily Briefing: editorial synthesis over processed/structured knowledge.

## V1 data flow

Abraham persisted outputs + recent processed documents + prior briefing history -> Daily Briefing -> one briefing per day.

V1 must not reprocess the Reader library and must not send the entire Reader corpus to a model.

## V2 data flow

Nayvadius structured Obsidian data -> Notion -> Daily Briefing -> one briefing per day.

The V2 interface should treat Notion/Nayvadius as the canonical knowledge source and Reader as an upstream ingestion system, not as a briefing source.

## Required briefing sections

1. Top 5: most important new developments/ideas.
2. What I should know: concise high-value takeaways.
3. Trends: patterns emerging across multiple items.
4. Connections: links to existing knowledge/entities.
5. Conflicts & uncertainty: contradictory, weak, or unresolved claims.
6. Economy/industry: material implications where supported.
7. Culture/music: meaningful cultural or musical implications where supported.
8. Long-term knowledge value: what deserves retention.
9. What changed since yesterday: only meaningful changes.
10. Bottom line: the smallest set of things worth remembering today.

## Quality rules

- Prefer synthesis over item-by-item summaries.
- Never invent a connection that is not supported by the supplied data.
- Separate facts, attributed claims, inference and uncertainty.
- Avoid repeating information that appeared in recent briefings unless it changed materially.
- Rank by importance, not by document color alone.
- Do not confuse Abraham's detailed Rating with Reader color tiers.
- Do not mutate Reader data.
- Keep the output useful even when the day's data volume is low.

## Cost rule

The briefing should consume compact, preprocessed records. It must not trigger bulk rereading, bulk translation, entity extraction, or detailed rating of Reader documents.

## Future interface contract

Nayvadius should eventually publish a compact daily briefing dataset containing:
- newly added knowledge items
- changed knowledge items
- canonical entities and relationships
- relevant existing knowledge links
- source/evidence metadata
- recent briefing history or change markers

The briefing engine consumes that dataset and writes the final daily briefing to Notion.
