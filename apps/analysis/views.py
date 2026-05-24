"""analysis explorer views — JSON feeds + HTMX partials + the page shell."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from analysis import services


@login_required
def explorer(request: HttpRequest) -> HttpResponse:
    """The full crosstalk-explorer page. Graph data is fetched async via JSON."""
    from networks.models import Network

    networks = list(
        Network.objects.values("code", "title", "category").order_by("category", "code")
    )
    return render(request, "analysis/explorer.html", {"networks": networks})


@login_required
def neighborhood_json(request: HttpRequest) -> JsonResponse:
    entity_id = request.GET.get("entity_id")
    if not entity_id:
        return JsonResponse({"error": "entity_id required"}, status=400)
    k = int(request.GET.get("k", 1))
    data = services.neighborhood(entity_id=int(entity_id), k=k)
    return JsonResponse(data)


@login_required
def crosstalk_json(request: HttpRequest) -> JsonResponse:
    a = request.GET.get("network_a")
    b = request.GET.get("network_b")
    if not a or not b:
        return JsonResponse({"error": "network_a and network_b required"}, status=400)
    return JsonResponse(services.crosstalk_edges(network_a=a, network_b=b))


@login_required
def paths_json(request: HttpRequest) -> JsonResponse:
    try:
        source = int(request.GET["source"])
        target = int(request.GET["target"])
    except (KeyError, ValueError):
        return JsonResponse({"error": "source and target required"}, status=400)
    mode = request.GET.get("mode", "shortest")
    max_len = int(request.GET.get("max_len", 6))
    if mode == "all":
        paths = services.all_simple_paths(
            source_entity=source, target_entity=target, max_len=max_len
        )
    else:
        paths = services.shortest_paths(source_entity=source, target_entity=target, max_len=max_len)
    return JsonResponse({"paths": paths})


@login_required
def analysis_panel(request: HttpRequest) -> HttpResponse:
    """HTMX partial: centrality ranking + communities + feedback loops.

    `network` (optional) scopes the GDS algorithms; `measure` selects the
    centrality measure; `max_len` bounds feedback-loop cycle length.
    """
    network = request.GET.get("network") or None
    measure = request.GET.get("measure", "pagerank")
    max_len = int(request.GET.get("max_len", 4))
    try:
        ranking = services.centrality(network=network, measure=measure)
    except ValueError:
        ranking = []
    context = {
        "measure": measure,
        "network": network,
        "centrality": ranking[:25],
        "communities": services.communities(network=network),
        "feedback_loops": services.feedback_loops(max_len=max_len, network=network),
    }
    return render(request, "analysis/_analysis_panel.html", context)
