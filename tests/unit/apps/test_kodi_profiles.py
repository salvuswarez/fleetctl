"""Profile inheritance, and the variant that drops platform-supplied addons."""

from __future__ import annotations

import pytest

from fleetctl.apps.kodi.merging import deep_merge
from fleetctl.apps.kodi.pack import KodiApp, _load_profile
from fleetctl.apps.kodi.transforms.addons import PruneAddons
from fleetctl.core.errors import FleetError

BINARY_PREFIX = "inputstream."
BINARY_EXACT = "pvr.iptvsimple"


def _prune(profile: str) -> PruneAddons:
    """RETURNS: PruneAddons: The prune transform from a profile's chain."""
    transform = KodiApp(profile).transforms[0]
    assert isinstance(transform, PruneAddons)
    return transform


def test_the_deck_profile_inherits_golds_settings() -> None:
    """The whole point of `extends`: the two profiles cannot drift apart on
    the hundred lines of settings neither of them changes."""
    # Act
    gold, deck = KodiApp("gold").recipe, KodiApp("deck").recipe

    # Assert
    assert deck["apply_settings"] == gold["apply_settings"]
    assert deck["apply_view_types"] == gold["apply_view_types"]
    # The hub layout is deliberately not inherited: the Deck's variant adds
    # rows for folders that exist on no other device.
    assert deck["apply_hub_layout"] != gold["apply_hub_layout"]


def test_the_resolved_recipe_does_not_carry_the_extends_key() -> None:
    # Act / Assert
    assert "extends" not in KodiApp("deck").recipe


def test_the_deck_profile_drops_the_binary_stream_engines() -> None:
    """These are compiled `.so` objects. The stick's are `armeabi-v7a` and a
    user-profile addon shadows the application image's native one."""
    # Act
    deck = _prune("deck")

    # Assert
    assert BINARY_PREFIX not in deck.allow_prefixes
    assert BINARY_EXACT not in deck.allow


def test_the_gold_profile_still_keeps_them() -> None:
    """A Fire Stick has no application image supplying them, so gold must
    carry its own. This variant must not leak back into gold."""
    # Act
    gold = _prune("gold")

    # Assert
    assert BINARY_PREFIX in gold.allow_prefixes
    assert BINARY_EXACT in gold.allow


def test_the_deck_profile_keeps_every_python_addon_gold_keeps() -> None:
    """Only the compiled entries differ; dropping a content addon or the skin
    would be a silent regression."""
    # Act
    gold, deck = _prune("gold"), _prune("deck")

    # Assert
    assert set(gold.allow) - set(deck.allow) == {BINARY_EXACT}
    assert set(gold.allow_prefixes) - set(deck.allow_prefixes) == {BINARY_PREFIX}


def test_a_list_replaces_rather_than_accumulates() -> None:
    """If lists merged by union, a variant could never remove an entry, which
    is the only reason this variant exists."""
    # Act
    merged = deep_merge({"prune_addons": {"allow": ["a", "b"]}}, {"prune_addons": {"allow": ["a"]}})

    # Assert
    assert merged["prune_addons"]["allow"] == ["a"]


def test_nested_mappings_merge_key_by_key() -> None:
    """So a variant can change one setting without restating its block."""
    # Act
    merged = deep_merge({"settings": {"x": "1", "y": "2"}}, {"settings": {"y": "9"}})

    # Assert
    assert merged["settings"] == {"x": "1", "y": "9"}


def test_merging_does_not_mutate_the_inherited_recipe() -> None:
    """Profiles are cached per process; mutating the parent would leak the
    child's overrides into every later load of it."""
    # Arrange
    base = {"prune_addons": {"allow": ["a"]}}

    # Act
    deep_merge(base, {"prune_addons": {"allow": ["b"]}})

    # Assert
    assert base == {"prune_addons": {"allow": ["a"]}}


def test_a_profile_that_extends_itself_is_rejected() -> None:
    """Silently recursing would exhaust the stack rather than name the file."""
    # Act / Assert
    with pytest.raises(FleetError, match="extends itself"):
        _load_profile("deck", _seen=("gold", "deck"))


def test_transforms_for_shapes_a_capture_with_another_devices_recipe() -> None:
    """One registered app serves the whole fleet. The instance the entry point
    builds defaults to `gold`, so a Deck build is only possible if a caller can
    name a different profile without constructing a second app."""
    # Arrange
    app = KodiApp()

    # Act
    chain = app.transforms_for("deck")

    # Assert
    assert chain != app.transforms
    assert chain == KodiApp("deck").transforms


def test_transforms_for_falls_back_to_the_default_profile() -> None:
    # Arrange
    app = KodiApp()

    # Act / Assert
    assert app.transforms_for(None) == app.transforms


def test_pinned_overrides_beat_a_named_profile() -> None:
    """A caller that supplied its own recipe means it; a device's profile name
    must not silently replace it."""
    # Arrange
    app = KodiApp(overrides={"prune_addons": {"allow": ["only.this"]}})

    # Act / Assert
    assert app.transforms_for("deck") == app.transforms


def test_an_unknown_profile_names_the_ones_that_ship() -> None:
    """A device pointed at a missing profile would otherwise fail deep in the
    transform chain, or build with the wrong recipe entirely."""
    # Act / Assert
    with pytest.raises(FleetError, match="No Kodi profile 'nope'"):
        KodiApp().transforms_for("nope")
