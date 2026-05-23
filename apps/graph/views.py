"""graph dev UI views.

Minimal — Phase 5 owns the full verification surface. These exist only
so Phase 3 can be demoed: load /graph/dev/networks/nfkb_axis/ and see
the NF-κB axis rendered with Cytoscape.js.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render

from graph.models import NetworkEdgeMembership


def dev_network(request: HttpRequest, code: str) -> HttpResponse:
    """Render the Cytoscape.js dev graph page for one network."""
    from networks.models import Network  # noqa: PLC0415

    network = get_object_or_404(Network, code=code)
    return render(request, "graph/dev_network.html", {"network": network})


def dev_network_edges_json(request: HttpRequest, code: str) -> JsonResponse:
    """Return nodes + edges JSON for the Cytoscape.js client."""
    from networks.models import Network  # noqa: PLC0415

    network = get_object_or_404(Network, code=code)

    memberships = (
        NetworkEdgeMembership.objects.filter(network=network)
        .select_related(
            "edge__source__ontology_entity",
            "edge__target__ontology_entity",
        )
        .prefetch_related(
            "edge__source__ontology_entity__identifiers",
            "edge__target__ontology_entity__identifiers",
        )
    )

    nodes: dict[int, dict] = {}
    edges: list[dict] = []

    for m in memberships:
        for entity in (m.edge.source, m.edge.target):
            if entity.pk in nodes:
                continue
            pri = entity.primary_identifier
            nodes[entity.pk] = {
                "data": {
                    "id": f"n{entity.pk}",
                    "label": entity.preferred_label,
                    "iri": pri.as_iri() if pri else "",
                    "entity_type": entity.ontology_entity.entity_type,
                },
            }
        edges.append(
            {
                "data": {
                    "id": f"e{m.edge.pk}",
                    "source": f"n{m.edge.source_id}",
                    "target": f"n{m.edge.target_id}",
                    "source_label": m.edge.source.preferred_label,
                    "target_label": m.edge.target.preferred_label,
                    "relation": m.edge.relation,
                    "belief": round(m.edge.belief_score, 3),
                    "status": m.edge.status,
                    "relevance": m.relevance,
                },
            }
        )

    return JsonResponse({"nodes": list(nodes.values()), "edges": edges})
