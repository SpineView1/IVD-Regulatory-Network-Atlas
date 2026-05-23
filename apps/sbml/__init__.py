"""sbml — versioned SBML-qual emission per network.

Owns ``ModelVersion`` (immutable per-version snapshot) and ``ExportArtifact``
(download audit). The only writer of these tables is ``sbml.tasks.regenerate``.

Public API: ``sbml.services``. Phase 5 (verification UI) imports
``sbml.services``, not the models or tasks directly.
"""
