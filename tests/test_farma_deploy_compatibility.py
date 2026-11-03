"""Compatibilidad de Les Enfants con despliegues previos a la hoja FARMA."""

from types import SimpleNamespace


def test_legacy_catalog_without_farma_attribute_is_safe():
    catalog = SimpleNamespace(route_cost_blocks=set(), warnings=[])
    farma_block_pairs = set(getattr(catalog, "farma_block_pairs", set()))
    catalog.route_cost_blocks |= farma_block_pairs
    assert catalog.route_cost_blocks == set()
