"""Example generator: one name and one infocard in the mod's resource DLL.

It proves the pipeline end to end (strings registry -> fcm_text.dll -> ``[Resources]`` patch)
and gives in-game tests a known IDS to look up: ``fcm.example.name`` resolves to
``ids_index * 65536 + local id`` (524289 on HDE with a fresh text-id map). It adds no game
nicknames; a generator that does must use the ``fcm_`` prefix (CONVENTIONS §2).
"""

ORDER = 900  # after real content generators


def generate(ctx) -> None:
    name_ids = ctx.strings.register("fcm.example.name", "Carrier Mod Test String")
    card_ids = ctx.strings.register(
        "fcm.example.infocard",
        "Carrier & Endgame mod test infocard.\n\nIf you can read this in game, the mod's "
        "resource DLL is loaded.",
        kind="infocard")
    ctx.log(f"registered IDS {name_ids} (name) and {card_ids} (infocard)")
