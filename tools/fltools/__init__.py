"""fltools: Freelancer data-format toolkit for the Carrier & Endgame mod.

Stdlib-only at runtime (Python >= 3.11). Modules:

- ``fltools.ini``         lossless FL text-INI reader/writer (+ case-insensitive path resolver)
- ``fltools.bini``        BINI (binary INI) decoder (optional; HDE ships none)
- ``fltools.hash``        CreateID, faction id (MakeId), location id
- ``fltools.peres``       PE resource reader (RT_STRING / RT_HTML) and global IDS resolution
- ``fltools.resdll``      resource-only x86 DLL builder (pure Python, or llvm-rc + lld-link)
- ``fltools.utf``         UTF container (.cmp/.3db/.mat/.txm) reader/writer + hardpoint helpers
- ``fltools.install``     an install (optionally combined with an overlay) as one virtual data tree
- ``fltools.validate``    cross-reference validator
- ``fltools.hashscan``    CreateID / faction-hash collision scan
- ``fltools.patch``       idempotent, reversible marker-block INI patch framework
- ``fltools.geometry``    zone/object rotation and containment conventions
- ``fltools.worldexport`` world.json exporter

Nothing in this package writes into a game install unless explicitly asked to by a caller
(``fltools.patch`` apply/unpatch on a path the caller gives).
"""

__version__ = "1.0.0"
