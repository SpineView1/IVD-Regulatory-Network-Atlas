"""graph — normalized entity/edge graph and aggregation pipeline.

Depends on:
  - core (OntologyEntity, Identifier, ground_mention)
  - networks (Network, root_entities)
  - extract (RawPPI, ExtractionRun)
  - papers (Chunk, Section)
  - corpus (Paper)

Spec §3 (data model), §4 (normalize_and_integrate), §7 (network state machine).
"""
